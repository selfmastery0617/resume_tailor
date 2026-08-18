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

from datetime import datetime, timezone
from typing import Any, Iterable
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


def active_profile_id(conn: Connection | None = None) -> UUID:
    """Which resume identity owns the jobs being imported and shown."""
    from app.services import settings_service

    configured = (settings_service.get_settings().get("resumeProfile") or "").strip()
    user_id = current_user_id()

    def resolve(c: Connection) -> UUID:
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
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else "",
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else "",
    }
    job["applied"] = row.application_status == "applied"
    # Nothing may act on an applied job. One flag, so the rule lives in one
    # place instead of being re-derived in every renderer.
    job["locked"] = job["applied"]
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
