"""Persistence for imported job listings.

Two rules shape everything here:

* **Re-importing updates, it does not duplicate.** `(profile_id, source,
  source_job_id)` is unique, so a second import of the same listing refreshes
  its details.
* **An applied job is a record, not a draft.** Once marked applied it stops
  being touched by imports and stops being usable as pipeline input.

Jobs belong to a profile, not directly to a user: one person keeps several
resume identities and each runs its own search. Until there is a profile
switcher in the UI, the active profile is the one named by the `resumeProfile`
setting, falling back to the user's default.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import Connection, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.bootstrap import current_user_id
from app.db import get_db
from app.ids import uuid7
from app.models import (
    application_events,
    extraction_runs,
    generated_documents,
    jobs,
    profiles,
    settings,
)
from app.schemas.job import JobListing

# Columns an import may refresh. Deliberately excludes the applied fields and
# first_seen_at.
_IMPORT_FIELDS = (
    "title",
    "company",
    "location",
    "url",
    "description",
    "salary_raw",
    "work_model",
    "match_score",
    "published_at",
    "skills",
)


class JobNotFound(LookupError):
    pass


class NoProfile(RuntimeError):
    """No profile exists to own imported jobs."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    """The calendar date to stamp a row with.

    Local, not UTC, unlike every timestamp here. A timestamp is an instant and
    belongs in UTC; "the date I added this" is a calendar date, and someone
    adding a job at 8pm expects today's date, not tomorrow's because the server
    is already past midnight in London.
    """
    return datetime.now().date()


def active_profile_id(conn: Connection | None = None) -> UUID:
    """Which resume identity owns the jobs being imported and shown."""
    user_id = current_user_id()

    def resolve(c: Connection) -> UUID:
        # Read resumeProfile directly rather than through
        # settings_service.get_settings(): that function scopes its own
        # result by calling back into active_profile_id() (via
        # _active_profile()), which would recurse forever if this used it
        # too — each level opening another DB connection until the pool
        # itself is exhausted, rather than a clean RecursionError.
        row = c.execute(
            select(settings.c.value).where(
                settings.c.scope == "user",
                settings.c.user_id == user_id,
                settings.c.key == "resumeProfile",
            )
        ).first()
        configured = str(row.value or "").strip() if row else ""

        if configured:
            try:
                found = c.execute(
                    select(profiles.c.id).where(profiles.c.id == UUID(configured))
                ).scalar()
            except ValueError:
                found = None
            if found:
                return found
        found = c.execute(
            select(profiles.c.id)
            .where(profiles.c.user_id == user_id)
            .order_by(profiles.c.is_default.desc(), profiles.c.created_at)
            .limit(1)
        ).scalar()
        if found is None:
            raise NoProfile(
                "Create a profile before importing jobs — a job belongs to the "
                "resume identity chasing it."
            )
        return found

    return resolve(conn) if conn is not None else _with_conn(resolve)


def _with_conn(fn):
    with get_db() as conn:
        return fn(conn)


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


_RELATIVE_PUBLISH_RE = re.compile(
    r"(?P<n>\d+)\s*(?P<unit>hour|day|week|month|year)s?\s*ago", re.IGNORECASE
)


def _parse_publish_time(listing: JobListing, now: datetime) -> datetime | None:
    """When Jobright says a listing was posted, as a best-effort absolute time.

    Jobright's own `publishTime` is undocumented and not reliably present (the
    mock fixtures only ever set the relative description), so the description
    — "2 days ago", "6 hours ago" — is the field actually trusted. `publish_time`
    is tried first in case it turns out to be an epoch or ISO value; either way
    a listing whose posting time can't be read just leaves the column empty
    rather than guessing, same as every other best-effort field here.
    """
    raw = (listing.publish_time or "").strip()
    if raw:
        try:
            return datetime.fromtimestamp(float(raw) / (1000 if len(raw) >= 13 else 1), tz=timezone.utc)
        except (ValueError, OSError):
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass

    text = (listing.publish_time_desc or "").strip().lower()
    if not text:
        return None
    if text in ("just now", "today"):
        return now
    if text == "yesterday":
        return now - timedelta(days=1)
    match = _RELATIVE_PUBLISH_RE.search(text)
    if not match:
        return None
    n = int(match.group("n"))
    unit = match.group("unit")
    delta = {
        "hour": timedelta(hours=n),
        "day": timedelta(days=n),
        "week": timedelta(weeks=n),
        "month": timedelta(days=n * 30),
        "year": timedelta(days=n * 365),
    }[unit]
    return now - delta


def _as_number(value: Any) -> float | None:
    """Jobright sends the match score as a string like '85' or '85%'."""
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except ValueError:
        return None


def _row_to_dict(row) -> dict[str, Any]:
    job = {
        "id": str(row.id),
        "source": row.source,
        "title": row.title,
        "company": row.company,
        "location": row.location,
        "url": row.url,
        "description": row.description,
        "salary": row.salary_raw,
        "work_model": row.work_model,
        "match_score": "" if row.match_score is None else str(row.match_score),
        "publish_time": row.published_at.isoformat() if row.published_at else "",
        "publish_time_desc": "",
        "skills": row.skills,
        "application_status": row.application_status,
        "date_added": row.date_added.isoformat() if row.date_added else "",
        # The three states the table shows: "" (nothing yet), Ready, Applied.
        "status": "" if row.application_status == "not_applied" else row.application_status,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else "",
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else "",
    }
    job["applied"] = row.application_status == "applied"
    # Nothing may act on an applied job. One flag, so the rule lives in one
    # place instead of being re-derived in every renderer.
    job["locked"] = job["applied"]
    # Status is only selectable once there is a resume to be ready with.
    job["hasResume"] = row.pipeline_state == "generated" or row.application_status != "not_applied"
    return job


def upsert_many(listings: Iterable[JobListing], source: str = "jobright") -> list[dict[str, Any]]:
    """Store an import. Returns every stored job.

    Rows already marked applied keep their details — re-importing must not
    rewrite the listing a submitted application was based on. Their
    `last_seen_at` still advances, so "this posting is still live" stays true.
    """
    now = _now()
    with get_db() as conn:
        profile_id = active_profile_id(conn)
        user_id = current_user_id()

        for listing in listings:
            statement = pg_insert(jobs).values(
                id=uuid7(),
                profile_id=profile_id,
                user_id=user_id,
                source=source,
                source_job_id=listing.id,
                title=_as_text(listing.title),
                company=_as_text(listing.company),
                location=_as_text(listing.location),
                url=_as_text(listing.url),
                description=_as_text(listing.description),
                salary_raw=_as_text(listing.salary),
                work_model=_as_text(listing.work_model),
                match_score=_as_number(listing.match_score),
                skills=_as_text(listing.skills),
                published_at=_parse_publish_time(listing, now),
                first_seen_at=now,
                last_seen_at=now,
            )
            refresh = {
                field: getattr(statement.excluded, field) for field in _IMPORT_FIELDS
            }
            refresh["last_seen_at"] = statement.excluded.last_seen_at
            conn.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        jobs.c.profile_id, jobs.c.source, jobs.c.source_job_id
                    ],
                    set_=refresh,
                    # Applied rows are records; only their last_seen_at moves,
                    # handled by the separate touch below.
                    where=jobs.c.application_status != "applied",
                )
            )

        conn.execute(
            jobs.update()
            .where(
                jobs.c.profile_id == profile_id,
                jobs.c.application_status == "applied",
                jobs.c.source_job_id.in_([listing.id for listing in listings] or [""]),
            )
            .values(last_seen_at=now)
        )
    return list_jobs()


def list_jobs() -> list[dict[str, Any]]:
    """Every stored job for the active profile. Not-yet-applied first."""
    with get_db() as conn:
        profile_id = active_profile_id(conn)
        rows = conn.execute(
            select(jobs)
            .where(jobs.c.profile_id == profile_id, jobs.c.archived_at.is_(None))
            .order_by(
                (jobs.c.application_status == "applied"),
                jobs.c.last_seen_at.desc(),
                jobs.c.company,
            )
        ).all()
    return [_row_to_dict(row) for row in rows]


def _find(conn: Connection, job_id: str):
    try:
        target = UUID(str(job_id))
    except ValueError:
        # Ids from the old SQLite store were the source's own id, not a UUID.
        return conn.execute(
            select(jobs).where(jobs.c.source_job_id == str(job_id))
        ).first()
    return conn.execute(select(jobs).where(jobs.c.id == target)).first()


def get_job(job_id: str) -> dict[str, Any]:
    with get_db() as conn:
        row = _find(conn, job_id)
    if row is None:
        raise JobNotFound(job_id)
    return _row_to_dict(row)


def is_locked(job_id: str) -> bool:
    """True once a job is applied. Called on every pipeline entry point."""
    with get_db() as conn:
        row = _find(conn, job_id)
    return row is not None and row.application_status == "applied"


def mark_applied(job_id: str) -> dict[str, Any]:
    """Record that this job was applied to, and freeze the row.

    Idempotent rather than an error on repeat: two clicks should not fail, and
    the first application date is the one worth keeping.
    """
    with get_db() as conn:
        row = _find(conn, job_id)
        if row is None:
            raise JobNotFound(job_id)
        if row.application_status != "applied":
            applied_at = _now()
            # The most recent document for this job is the one that was sent.
            document_id = conn.execute(
                select(generated_documents.c.id)
                .where(generated_documents.c.job_id == row.id)
                .order_by(generated_documents.c.generated_at.desc())
                .limit(1)
            ).scalar()
            conn.execute(
                jobs.update()
                .where(jobs.c.id == row.id)
                .values(
                    application_status="applied",
                    applied_at=applied_at,
                    applied_document_id=document_id,
                    updated_at=func.now(),
                )
            )
            # The status is where it stands; the event log is how it got there.
            conn.execute(
                application_events.insert().values(
                    id=uuid7(),
                    job_id=row.id,
                    kind="applied",
                    occurred_at=applied_at,
                    document_id=document_id,
                )
            )
        return _row_to_dict(_find(conn, str(row.id)))


def delete_job(job_id: str) -> dict[str, Any]:
    """Remove a job and everything derived from it.

    Extraction runs, bullets, application events and document rows cascade.
    Files already written to the output folder are left alone — deleting a
    document someone may have sent is not this button's job — and the caller is
    told what remains.
    """
    with get_db() as conn:
        row = _find(conn, job_id)
        if row is None:
            raise JobNotFound(job_id)

        orphan = conn.execute(
            select(generated_documents.c.storage_key)
            .where(
                generated_documents.c.job_id == row.id,
                generated_documents.c.storage_key.isnot(None),
            )
            .order_by(generated_documents.c.generated_at.desc())
            .limit(1)
        ).scalar()

        conn.execute(delete(jobs).where(jobs.c.id == row.id))

    return {
        "deleted": str(row.id),
        "title": row.title,
        "company": row.company,
        "orphanedFile": orphan,
    }


def run_for_job(conn: Connection, job_id: str) -> UUID | None:
    """The most recent extraction run id for a job, if any."""
    row = _find(conn, job_id)
    if row is None:
        return None
    return conn.execute(
        select(extraction_runs.c.id)
        .where(extraction_runs.c.job_id == row.id)
        .order_by(extraction_runs.c.started_at.desc())
        .limit(1)
    ).scalar()


# --- editing -----------------------------------------------------------------

# What the table may change. Everything else about a job comes from the import
# or from the pipeline.
EDITABLE_FIELDS = ("date_added", "title", "company", "url", "location", "status", "description")

# The two a person may choose between. 'not_applied' is reachable only by the
# application clearing a row, never by a user: "no resume yet" is a fact about
# the row, not a choice someone makes.
SELECTABLE_STATUSES = ("ready", "applied")


class JobLocked(RuntimeError):
    """The edit is refused because the row is in a state that forbids it."""


def _valid_url(value: str) -> bool:
    """Good enough to decide whether a description can be fetched for it."""
    text = (value or "").strip()
    if not text:
        return False
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return bool(parsed.scheme in ("http", "https") and parsed.netloc and "." in parsed.netloc)


def _coerce_date(value: Any) -> date | None:
    """Accept what a person or a spreadsheet paste actually types."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{value!r} is not a date the table understands (use YYYY-MM-DD).")


def _has_resume(conn: Connection, job_id: UUID) -> bool:
    return conn.execute(
        select(generated_documents.c.id)
        .where(generated_documents.c.job_id == job_id)
        .limit(1)
    ).scalar() is not None


def create_job(fields: dict[str, Any]) -> dict[str, Any]:
    """A row typed or pasted into the empty row at the bottom of the table."""
    now = _now()
    with get_db() as conn:
        profile_id = active_profile_id(conn)
        job_id = uuid7()
        conn.execute(
            jobs.insert().values(
                id=job_id,
                profile_id=profile_id,
                user_id=current_user_id(),
                source="manual",
                # Its own id keeps (profile, source, source_job_id) meaningful
                # without ever colliding with something imported.
                source_job_id=str(job_id),
                title=str(fields.get("title") or ""),
                company=str(fields.get("company") or ""),
                location=str(fields.get("location") or ""),
                url=str(fields.get("url") or ""),
                description=str(fields.get("description") or ""),
                # A row is dated the day it appears, unless one was supplied.
                date_added=_coerce_date(fields.get("date_added")) or _today(),
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        return _row_to_dict(_find(conn, str(job_id)))


def update_job(job_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Apply one edit from the table.

    Three rules live here rather than in the UI, so a keystroke, a paste and a
    direct API call all behave identically:

    * a row with no date gets today's on any edit, and a row that has one keeps
      it;
    * clearing the URL clears the description and the generated resume with it,
      because neither can be trusted once the posting they came from is gone;
    * status is only selectable once a resume exists.
    """
    unknown = set(patch) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"Not editable: {', '.join(sorted(unknown))}")

    with get_db() as conn:
        row = _find(conn, job_id)
        if row is None:
            raise JobNotFound(job_id)

        values: dict[str, Any] = {}

        for field in ("title", "company", "location", "url", "description"):
            if field in patch:
                values[field] = str(patch[field] or "").strip()

        if "date_added" in patch:
            values["date_added"] = _coerce_date(patch["date_added"])

        if "status" in patch:
            wanted = str(patch["status"] or "").strip().lower()
            if wanted not in SELECTABLE_STATUSES:
                raise ValueError(f"Status must be one of {', '.join(SELECTABLE_STATUSES)}.")
            if not _has_resume(conn, row.id):
                raise JobLocked("Generate a resume for this job before setting its status.")
            values["application_status"] = wanted
            # applied_at pairs with the status, and the CHECK enforces it both ways.
            values["applied_at"] = _now() if wanted == "applied" else None
            if wanted == "applied":
                conn.execute(
                    application_events.insert().values(
                        id=uuid7(), job_id=row.id, kind="applied",
                        occurred_at=values["applied_at"],
                    )
                )

        # Losing the URL invalidates everything derived from the posting.
        if "url" in values and not _valid_url(values["url"]):
            values["description"] = ""
            values["pipeline_state"] = "imported"
            values["application_status"] = "not_applied"
            values["applied_at"] = None
            conn.execute(
                delete(generated_documents).where(generated_documents.c.job_id == row.id)
            )
            conn.execute(delete(extraction_runs).where(extraction_runs.c.job_id == row.id))

        # Auto-stamp. Checked after the patch, so an explicit date still wins.
        if values.get("date_added") is None and row.date_added is None:
            values["date_added"] = _today()

        if values:
            values["updated_at"] = func.now()
            conn.execute(jobs.update().where(jobs.c.id == row.id).values(**values))

        return _row_to_dict(_find(conn, str(row.id)))


def delete_many(job_ids: list[str]) -> dict[str, Any]:
    """Remove whole rows. Deliberately distinct from clearing their cells."""
    removed: list[str] = []
    with get_db() as conn:
        for job_id in job_ids:
            row = _find(conn, job_id)
            if row is None:
                continue
            conn.execute(delete(jobs).where(jobs.c.id == row.id))
            removed.append(str(row.id))
    return {"deleted": removed, "count": len(removed)}


def mark_ready(job_id: str) -> None:
    """A resume exists, so this row is ready to send.

    Only moves a row nobody has applied to — regenerating a resume for a job
    already marked applied must not walk its status backwards.
    """
    with get_db() as conn:
        row = _find(conn, job_id)
        if row is None:
            return
        conn.execute(
            jobs.update()
            .where(jobs.c.id == row.id, jobs.c.application_status == "not_applied")
            .values(application_status="ready", updated_at=func.now())
        )
