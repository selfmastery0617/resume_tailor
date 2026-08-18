"""Copy the SQLite data into PostgreSQL.

    python scripts/migrate_to_postgres.py            # dry run, writes nothing
    python scripts/migrate_to_postgres.py --apply    # actually copy
    python scripts/migrate_to_postgres.py --apply --replace   # wipe target first

Reads the old database, never writes to it. The SQLite file is left exactly as
it was, so rolling back is unsetting DATABASE_URL.

Run scripts/migration_plan.py first for a summary of what is about to move.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import delete, select  # noqa: E402

from app.bootstrap import ensure_bootstrap  # noqa: E402
from app.db import LEGACY_SQLITE_PATH, get_db  # noqa: E402
from app.ids import uuid7  # noqa: E402
from app.models import (  # noqa: E402
    extraction_bullets,
    extraction_roles,
    extraction_runs,
    generated_documents,
    jobs,
    profile_educations,
    profile_experiences,
    profile_skills,
    profile_template_settings,
    profiles,
    prompts,
    settings,
    templates,
    templates_versions,
)
from app.services.settings_service import PROMPT_KEYS  # noqa: E402

# Emptied by --replace, children first.
OWNED_TABLES = (
    extraction_bullets,
    extraction_roles,
    extraction_runs,
    generated_documents,
    jobs,
    profile_experiences,
    profile_educations,
    profile_skills,
    profile_template_settings,
    profiles,
    settings,
    prompts,
)

_INFO_COLUMNS = {
    "fullName": "full_name",
    "professionalTitle": "professional_title",
    "email": "email",
    "phone": "phone",
    "street": "street",
    "city": "city",
    "state": "state",
    "postal": "postal",
    "birthday": "birthday",
    "linkedin": "linkedin",
    "website": "website",
    "summary": "summary",
}


def parse_ts(value: Any) -> datetime:
    """The old store wrote ISO strings; timestamptz wants a datetime."""
    if isinstance(value, datetime):
        return value
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_legacy() -> sqlite3.Connection:
    if not LEGACY_SQLITE_PATH.exists():
        raise SystemExit(f"No SQLite database at {LEGACY_SQLITE_PATH}")
    conn = sqlite3.connect(f"file:{LEGACY_SQLITE_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def migrate(apply: bool, replace: bool) -> dict[str, int]:
    old = read_legacy()
    counts: dict[str, int] = {}
    notes: list[str] = []

    org_id, user_id = ensure_bootstrap()

    with get_db() as pg:
        existing = pg.execute(select(profiles.c.id)).first()
        if existing and not replace:
            raise SystemExit(
                "The target already holds profiles. Re-run with --replace to "
                "discard them, or migrate into an empty database."
            )
        if replace and apply:
            for table in OWNED_TABLES:
                pg.execute(delete(table))
            pg.execute(delete(templates).where(templates.c.source == "user"))

        # -- profiles ------------------------------------------------------
        profile_ids: dict[str, UUID] = {}
        # The old store allowed two profiles to share a name; the new one does
        # not. Renaming the later duplicate keeps both rather than making the
        # migration choose which piece of the user's work to discard.
        used_names: set[str] = set()
        renamed: list[str] = []

        def unique_name(name: str) -> str:
            candidate = name or "Untitled"
            suffix = 2
            while candidate.casefold() in used_names:
                candidate = f"{name} ({suffix})"
                suffix += 1
            if candidate != name:
                renamed.append(f"{name!r} -> {candidate!r}")
            used_names.add(candidate.casefold())
            return candidate

        for index, row in enumerate(old.execute("SELECT * FROM profiles ORDER BY created_at")):
            data = json.loads(row["data_json"] or "{}")
            info = data.get("profile") or {}
            new_id = uuid7()
            profile_ids[row["id"]] = new_id

            values: dict[str, Any] = {
                "id": new_id,
                "user_id": user_id,
                "name": unique_name(row["name"]),
                # The first profile becomes the default; the partial unique
                # index permits exactly one.
                "is_default": index == 0,
                "created_at": parse_ts(row["created_at"]),
                "updated_at": parse_ts(row["updated_at"]),
            }
            values.update({col: (info.get(field) or "") for field, col in _INFO_COLUMNS.items()})
            if apply:
                pg.execute(profiles.insert().values(**values))

            for order, item in enumerate(data.get("experience") or []):
                if apply:
                    pg.execute(profile_experiences.insert().values(
                        id=uuid7(), profile_id=new_id, user_id=user_id,
                        company=item.get("company") or "", title=item.get("title") or "",
                        location=item.get("location") or "",
                        start_date=item.get("startDate") or "",
                        # The CHECK forbids an end date on a current role.
                        end_date="" if item.get("current") else (item.get("endDate") or ""),
                        is_current=bool(item.get("current")),
                        description=item.get("description") or "", sort_order=order,
                    ))
                counts["profile_experiences"] = counts.get("profile_experiences", 0) + 1

            for order, item in enumerate(data.get("education") or []):
                if apply:
                    pg.execute(profile_educations.insert().values(
                        id=uuid7(), profile_id=new_id, user_id=user_id,
                        university=item.get("university") or "", degree=item.get("degree") or "",
                        start_year=item.get("startYear") or "", end_year=item.get("endYear") or "",
                        location=item.get("location") or "", sort_order=order,
                    ))
                counts["profile_educations"] = counts.get("profile_educations", 0) + 1

            seen: set[str] = set()
            for order, item in enumerate(data.get("skills") or []):
                name = (item.get("name") or "").strip()
                if not name or name.casefold() in seen:
                    continue
                seen.add(name.casefold())
                if apply:
                    pg.execute(profile_skills.insert().values(
                        id=uuid7(), profile_id=new_id, user_id=user_id, name=name,
                        category=item.get("category") or "Other", sort_order=order,
                    ))
                counts["profile_skills"] = counts.get("profile_skills", 0) + 1

            counts["profiles"] = counts.get("profiles", 0) + 1

        # -- user templates -------------------------------------------------
        template_ids: dict[str, UUID] = {}
        if has_table(old, "template_definitions"):
            for row in old.execute("SELECT * FROM template_definitions WHERE source='user'"):
                new_id = uuid7()
                template_ids[row["id"]] = new_id
                if apply:
                    pg.execute(templates.insert().values(
                        # A user template must have an org: the CHECK reads
                        # (source = 'builtin') = (org_id IS NULL), and it is
                        # evaluated on insert, not at commit.
                        id=new_id, org_id=org_id, owner_user_id=user_id, key=row["id"],
                        name=row["name"], description=row["description"] or "",
                        source="user", visibility="private",
                        renderer_key=row["renderer_key"],
                        current_version=row["version"], is_active=bool(row["active"]),
                        created_at=parse_ts(row["created_at"]),
                        updated_at=parse_ts(row["updated_at"]),
                    ))
                    pg.execute(templates_versions.insert().values(
                        id=uuid7(), template_id=new_id, version=row["version"],
                        layout=json.loads(row["layout_json"] or "{}"),
                        default_style=json.loads(row["default_style_json"] or "{}"),
                    ))
                counts["templates"] = counts.get("templates", 0) + 1

        def template_uuid(key: str | None) -> UUID | None:
            if not key:
                return None
            if key in template_ids:
                return template_ids[key]
            return pg.execute(select(templates.c.id).where(templates.c.key == key)).scalar()

        # -- per-profile template settings -----------------------------------
        for row in old.execute("SELECT * FROM profile_template_settings"):
            target = profile_ids.get(row["profile_id"])
            if target is None:
                continue
            if apply:
                pg.execute(profile_template_settings.insert().values(
                    profile_id=target, user_id=user_id,
                    template_id=template_uuid(row["template_id"]) or template_uuid("template-1"),
                    template_version=row["template_version"],
                    style_overrides=json.loads(row["style_overrides_json"] or "{}"),
                    updated_at=parse_ts(row["updated_at"]),
                ))
            counts["profile_template_settings"] = counts.get("profile_template_settings", 0) + 1

        # -- settings and prompts ---------------------------------------------
        default_profile = next(iter(profile_ids.values()), None)
        for row in old.execute("SELECT * FROM app_settings"):
            key, value = row["key"], json.loads(row["value_json"])
            if key == "resumeProfile" and value:
                # Ids changed, so the pointer has to be remapped or dropped.
                value = str(profile_ids.get(str(value), "")) or ""
            if kind := PROMPT_KEYS.get(key):
                if apply:
                    pg.execute(prompts.insert().values(
                        id=uuid7(), scope="user", user_id=user_id, kind=kind,
                        body=str(value),
                    ))
                counts["prompts"] = counts.get("prompts", 0) + 1
            else:
                if apply:
                    pg.execute(settings.insert().values(
                        id=uuid7(), scope="user", user_id=user_id, key=key, value=value,
                    ))
                counts["settings"] = counts.get("settings", 0) + 1

        # -- jobs ---------------------------------------------------------------
        job_ids: dict[str, UUID] = {}
        if has_table(old, "jobs") and default_profile:
            for row in old.execute("SELECT * FROM jobs"):
                new_id = uuid7()
                job_ids[row["id"]] = new_id
                applied = row["application_status"] == "applied"
                if apply:
                    pg.execute(jobs.insert().values(
                        id=new_id, profile_id=default_profile, user_id=user_id,
                        source=row["source"], source_job_id=row["id"],
                        title=row["title"], company=row["company"],
                        location=row["location"], url=row["url"],
                        description=row["description"], salary_raw=row["salary"],
                        work_model=row["work_model"], skills=row["skills"],
                        application_status=row["application_status"],
                        applied_at=parse_ts(row["applied_at"]) if applied else None,
                        first_seen_at=parse_ts(row["first_seen_at"]),
                        last_seen_at=parse_ts(row["last_seen_at"]),
                    ))
                counts["jobs"] = counts.get("jobs", 0) + 1

        # -- extractions ---------------------------------------------------------
        stubs = 0
        for row in old.execute("SELECT * FROM job_experience"):
            payload = json.loads(row["payload_json"] or "{}")
            target = job_ids.get(row["job_id"])

            if target is None:
                # The job is gone, but its bullets are real work. Keep them
                # against a stub that says plainly where it came from.
                if not default_profile:
                    continue
                target = uuid7()
                job_ids[row["job_id"]] = target
                stubs += 1
                if apply:
                    pg.execute(jobs.insert().values(
                        id=target, profile_id=default_profile, user_id=user_id,
                        source="recovered", source_job_id=row["job_id"],
                        title="(recovered extraction)", company="",
                        description="", archived_at=parse_ts(row["updated_at"]),
                        first_seen_at=parse_ts(row["updated_at"]),
                        last_seen_at=parse_ts(row["updated_at"]),
                    ))

            search = payload.get("search") or {}
            run_id = uuid7()
            if apply:
                pg.execute(extraction_runs.insert().values(
                    id=run_id, job_id=target, user_id=user_id, state="succeeded",
                    summary=payload.get("summary") or "",
                    generator=payload.get("generator") or "fallback",
                    search_mode=search.get("mode") or "lexical",
                    search_model=search.get("model") or "",
                    provider_turns=int(payload.get("deepseekTurns") or 0),
                    started_at=parse_ts(row["updated_at"]),
                    finished_at=parse_ts(row["updated_at"]),
                ))
            counts["extraction_runs"] = counts.get("extraction_runs", 0) + 1

            for slot in ("job1", "job2"):
                selection = payload.get(slot) or {}
                if not selection:
                    continue
                role_id = uuid7()
                if apply:
                    pg.execute(extraction_roles.insert().values(
                        id=role_id, run_id=run_id, slot=slot,
                        company_name=selection.get("company") or "",
                        product_name=selection.get("product") or "",
                        timeline=selection.get("timeline") or "",
                    ))
                counts["extraction_roles"] = counts.get("extraction_roles", 0) + 1

                bullets = [b for b in (selection.get("bullets") or []) if b]
                if bullets and apply:
                    pg.execute(extraction_bullets.insert(), [
                        {"id": uuid7(), "role_id": role_id, "position": i, "text": t}
                        for i, t in enumerate(bullets)
                    ])
                counts["extraction_bullets"] = counts.get("extraction_bullets", 0) + len(bullets)

        if stubs:
            notes.append(f"{stubs} extraction(s) kept against a stub job, archived")

        # -- documents -------------------------------------------------------------
        saved_paths = {}
        if has_table(old, "job_resume"):
            for row in old.execute("SELECT * FROM job_resume"):
                saved_paths[row["job_id"]] = row

        unattributed = 0
        for row in old.execute("SELECT * FROM generated_resumes ORDER BY generated_at"):
            target_profile = profile_ids.get(row["profile_id"] or "")
            if target_profile is None:
                # The profile was deleted, and the old schema set the column to
                # NULL rather than removing the row. A document has to belong to
                # somebody now, and guessing an owner would be worse than saying
                # the record cannot be attributed.
                unattributed += 1
                continue
            job_key = row["job_application_id"]
            saved = saved_paths.pop(job_key, None) if job_key else None
            if apply:
                pg.execute(generated_documents.insert().values(
                    id=uuid7(), profile_id=target_profile, user_id=user_id,
                    job_id=job_ids.get(job_key or ""), run_id=None, kind="resume",
                    template_id=template_uuid(row["template_id"]),
                    template_version=row["template_version"],
                    content_snapshot=json.loads(row["profile_snapshot_json"] or "{}"),
                    style_snapshot=json.loads(row["style_snapshot_json"] or "{}"),
                    layout_snapshot=json.loads(row["layout_snapshot_json"] or "{}"),
                    file_name=row["file_name"],
                    storage_key=(saved["file_path"] if saved else row["file_path"]),
                    byte_size=saved["byte_size"] if saved else 0,
                    page_count=saved["page_count"] if saved else 0,
                    content_hash=row["content_hash"] or "",
                    generated_at=parse_ts(row["generated_at"]),
                ))
            counts["generated_documents"] = counts.get("generated_documents", 0) + 1

        # A saved resume with no matching generated_resumes row still describes
        # a real file; carry it rather than losing the only record of it.
        for job_key, saved in saved_paths.items():
            target_profile = profile_ids.get(saved["profile_id"] or "") or default_profile
            if target_profile is None:
                continue
            if apply:
                pg.execute(generated_documents.insert().values(
                    id=uuid7(), profile_id=target_profile, user_id=user_id,
                    job_id=job_ids.get(job_key), kind="resume",
                    template_id=template_uuid(saved["template_id"]),
                    template_version=1, file_name=saved["file_name"],
                    storage_key=saved["file_path"], byte_size=saved["byte_size"],
                    page_count=saved["page_count"],
                    generated_at=parse_ts(saved["generated_at"]),
                ))
            counts["generated_documents"] = counts.get("generated_documents", 0) + 1

        if renamed:
            notes.append(
                "renamed to satisfy the new unique profile name: "
                + "; ".join(renamed)
            )

        if unattributed:
            notes.append(
                f"{unattributed} generated_resumes row(s) had no profile (deleted "
                "before this migration) and were not carried across — a document "
                "must have an owner now"
            )

        if not apply:
            raise _Rollback(counts, notes)

    old.close()
    for note in notes:
        print(f"  note: {note}")
    return counts


class _Rollback(Exception):
    def __init__(self, counts, notes):
        self.counts, self.notes = counts, notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually write")
    parser.add_argument("--replace", action="store_true", help="empty the target first")
    args = parser.parse_args()

    try:
        counts = migrate(args.apply, args.replace)
        notes: list[str] = []
    except _Rollback as rollback:
        counts, notes = rollback.counts, rollback.notes
        print("DRY RUN — nothing was written\n")
    else:
        print("MIGRATED\n")

    for table, count in sorted(counts.items()):
        print(f"  {table:28} {count:5}")
    print(f"  {'-' * 28} {'-' * 5}")
    print(f"  {'total':28} {sum(counts.values()):5}")
    for note in notes:
        print(f"\n  note: {note}")
    if not args.apply:
        print("\nRe-run with --apply to write.")


if __name__ == "__main__":
    main()
