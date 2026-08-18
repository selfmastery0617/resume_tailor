"""Dry run: what the existing SQLite data becomes in the Postgres schema.

Reads only. Produces the rows that *would* be written, so the shape of the
migration — and anything that cannot be carried across — is visible before a
server is involved.

    python scripts/migration_plan.py

The write half lands once there is a database to write to; keeping the read and
transform separate means this part is testable now and stays testable after.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

SQLITE_PATH = BACKEND_ROOT / "data" / "jobtailor.sqlite3"
CORPUS_PATH = BACKEND_ROOT / "data" / "database.json"

def _unmapped_profile_fields() -> tuple[str, ...]:
    """ProfileInfo fields with no column on the new profiles table.

    Derived from both schemas rather than hardcoded, so adding a field to one
    side and forgetting the other shows up here instead of at migration time.
    """
    # app.models re-exports the Table itself under this name, not the module.
    from app.models.profiles import profiles as profiles_table
    from app.schemas.resume import ProfileInfo

    columns = set(profiles_table.columns.keys())

    def snake(name: str) -> str:
        import re

        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

    return tuple(
        field for field in ProfileInfo.model_fields if snake(field) not in columns
    )


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _split_timeline(raw: str) -> tuple[int | None, int | None, bool]:
    """"2019 - 2022" -> (2019, 2022, False). Mirrors tailored_resume_service."""
    import re

    text = (raw or "").strip()
    if not text:
        return None, None, False
    parts = [p.strip() for p in re.split(r"\s*[-–—]\s*", text, maxsplit=1)]

    def year(value: str) -> int | None:
        found = re.search(r"\b(19|20)\d{2}\b", value or "")
        return int(found.group()) if found else None

    start = year(parts[0])
    if len(parts) == 1:
        # A bare year says when it started and nothing about the end.
        return start, None, False
    if not parts[1] or parts[1].lower() in ("present", "current", "now"):
        return start, None, True
    return start, year(parts[1]), False


def plan() -> dict[str, Any]:
    if not SQLITE_PATH.exists():
        raise SystemExit(f"No SQLite database at {SQLITE_PATH}")

    out: dict[str, Any] = {"targets": Counter(), "warnings": [], "notes": []}
    conn = _connect(SQLITE_PATH)

    # -- corpus: database.json -> companies/products/projects/challenges ------
    if CORPUS_PATH.exists():
        raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8-sig"))
        entries = raw if isinstance(raw, list) else raw.get("entries", raw.get("companies", []))
        companies: dict[str, int] = {}
        skills: set[str] = set()
        products = projects = challenges = 0
        for entry in entries:
            companies.setdefault(entry.get("company", ""), 0)
            companies[entry.get("company", "")] += 1
            products += 1
            start, end, current = _split_timeline(entry.get("timeline", ""))
            if start is None and entry.get("timeline"):
                out["warnings"].append(
                    f"product {entry.get('product')!r}: timeline "
                    f"{entry.get('timeline')!r} has no parseable year"
                )
            for project in entry.get("projects", []):
                projects += 1
                for challenge in project.get("challenges", []):
                    challenges += 1
                    skills.update(challenge.get("skills_used", []))
                    if not challenge.get("id"):
                        out["warnings"].append("a challenge has no id to use as its slug")
        out["targets"].update({
            "companies": len(companies),
            "products": products,
            "projects": projects,
            "challenges": challenges,
            "skills": len(skills),
        })
        out["notes"].append(f"corpus companies: {', '.join(sorted(c for c in companies if c))}")
    else:
        out["warnings"].append(f"{CORPUS_PATH.name} not found — corpus tables would be empty")

    # -- profiles -> profiles + normalised sections ---------------------------
    empty_profiles: list[str] = []
    dropped_fields: Counter = Counter()
    experiences = educations = profile_skills = 0
    unmapped = _unmapped_profile_fields()
    if unmapped:
        out["notes"].append(
            "profile fields with no column on the new table: " + ", ".join(unmapped)
        )

    for row in conn.execute("SELECT id, name, data_json FROM profiles").fetchall():
        data = json.loads(row["data_json"] or "{}")
        info = data.get("profile") or {}
        exp = data.get("experience") or []
        edu = data.get("education") or []
        sk = data.get("skills") or []
        experiences += len(exp)
        educations += len(edu)
        profile_skills += len(sk)

        for field in unmapped:
            if (info.get(field) or "").strip():
                dropped_fields[field] += 1

        if not any([info.get("fullName"), exp, edu, sk]):
            empty_profiles.append(row["name"])

    out["targets"].update({
        "profiles": conn.execute("SELECT COUNT(*) n FROM profiles").fetchone()["n"],
        "profile_experiences": experiences,
        "profile_educations": educations,
        "profile_skills": profile_skills,
    })
    if empty_profiles:
        out["notes"].append(
            f"{len(empty_profiles)} profile(s) hold no resume content: "
            + ", ".join(repr(n) for n in empty_profiles)
        )
    for field, count in dropped_fields.items():
        out["warnings"].append(
            f"profiles.{field} is set on {count} profile(s) but the new schema "
            f"has no column for it — it would be lost"
        )

    # -- jobs -----------------------------------------------------------------
    if _table_exists(conn, "jobs"):
        jobs = conn.execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
        applied = conn.execute(
            "SELECT COUNT(*) n FROM jobs WHERE application_status = 'applied'"
        ).fetchone()["n"]
        out["targets"]["jobs"] = jobs
        out["notes"].append(f"{applied} of {jobs} jobs are marked applied")
    else:
        out["targets"]["jobs"] = 0
        out["warnings"].append(
            "no jobs table in this database — it lives on the "
            "feature/job-applied-delete branch, so run that branch's app once first"
        )

    # -- extractions ----------------------------------------------------------
    runs = roles = bullets = 0
    orphans: list[str] = []
    known_jobs = set()
    if _table_exists(conn, "jobs"):
        known_jobs = {r["id"] for r in conn.execute("SELECT id FROM jobs").fetchall()}

    for row in conn.execute("SELECT job_id, payload_json FROM job_experience").fetchall():
        payload = json.loads(row["payload_json"] or "{}")
        runs += 1
        for key in ("job1", "job2"):
            role = payload.get(key) or {}
            if role:
                roles += 1
                bullets += len(role.get("bullets") or [])
        if row["job_id"] not in known_jobs:
            orphans.append(row["job_id"])

    out["targets"].update({
        "extraction_runs": runs,
        "extraction_roles": roles,
        "extraction_bullets": bullets,
    })
    if orphans:
        out["warnings"].append(
            f"{len(orphans)} extraction(s) reference a job that no longer exists; "
            "they need a stub job or they cannot be carried across"
        )

    # -- documents ------------------------------------------------------------
    generated = conn.execute("SELECT COUNT(*) n FROM generated_resumes").fetchone()["n"]
    resumes = conn.execute("SELECT COUNT(*) n FROM job_resume").fetchone()["n"]
    missing_files = 0
    for row in conn.execute("SELECT file_path FROM job_resume").fetchall():
        if row["file_path"] and not Path(row["file_path"]).is_file():
            missing_files += 1
    out["targets"]["generated_documents"] = generated
    out["notes"].append(
        f"generated_resumes {generated} + job_resume {resumes} merge into one table"
    )
    if missing_files:
        out["warnings"].append(
            f"{missing_files} saved resume file(s) are no longer on disk; the row "
            "migrates but storage_key will point at nothing"
        )

    # -- settings and templates ----------------------------------------------
    settings_rows = conn.execute("SELECT key FROM app_settings").fetchall()
    keys = {r["key"] for r in settings_rows}
    prompt_keys = {"skillsPrompt", "tailoringPrompt", "summaryPrompt"} & keys
    out["targets"]["settings"] = len(keys - prompt_keys)
    out["targets"]["prompts"] = len(prompt_keys)
    if "resumeProfile" in keys:
        out["notes"].append(
            "resumeProfile is dropped by design — the profile becomes the context"
        )
    out["targets"]["templates"] = conn.execute(
        "SELECT COUNT(*) n FROM template_definitions"
    ).fetchone()["n"]
    out["targets"]["profile_template_settings"] = conn.execute(
        "SELECT COUNT(*) n FROM profile_template_settings"
    ).fetchone()["n"]

    conn.close()
    return out


def main() -> None:
    result = plan()

    print(f"source: {SQLITE_PATH}\n")
    print("would create")
    print("-" * 46)
    for table, count in sorted(result["targets"].items()):
        print(f"  {table:28} {count:5}")
    print("-" * 46)
    print(f"  {'total rows':28} {sum(result['targets'].values()):5}\n")

    if result["notes"]:
        print("notes")
        for note in result["notes"]:
            print(f"  - {note}")
        print()

    if result["warnings"]:
        print("needs a decision")
        for warning in result["warnings"]:
            print(f"  ! {warning}")
    else:
        print("no blockers found")


if __name__ == "__main__":
    main()
