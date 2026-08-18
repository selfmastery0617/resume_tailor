"""Persistence for imported job listings.

Jobs used to be returned straight to the browser and never stored, so the table
emptied on reload and every extraction was keyed to a row that did not exist.

Two rules shape everything here:

* **Re-importing updates, it does not duplicate.** The source's id is the
  primary key, so a second import of the same listing refreshes its details.
* **An applied job is a record, not a draft.** Once marked applied it stops
  being touched by imports and stops being usable as pipeline input.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.db import get_db
from app.schemas.job import JobListing

# Columns an import is allowed to refresh. Deliberately excludes the applied
# fields and first_seen_at.
_IMPORT_FIELDS = (
    "source",
    "title",
    "company",
    "location",
    "url",
    "description",
    "salary",
    "work_model",
    "match_score",
    "publish_time",
    "publish_time_desc",
    "skills",
)


class JobNotFound(LookupError):
    pass


class JobLocked(RuntimeError):
    """Raised when an action would modify a job already marked applied."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _row_to_dict(row) -> dict[str, Any]:
    job = {key: row[key] for key in row.keys()}
    # The grid reads these directly; keep them booleans rather than making the
    # frontend compare strings.
    job["applied"] = row["application_status"] == "applied"
    # Nothing may act on an applied job. One flag, so the rule lives in one
    # place instead of being re-derived in each renderer.
    job["locked"] = job["applied"]
    return job


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def upsert_many(listings: Iterable[JobListing], source: str = "jobright") -> list[dict[str, Any]]:
    """Store an import. Returns every stored job, newest import first.

    Rows already marked applied keep their details: re-importing must not
    rewrite the listing a submitted application was based on. Their
    ``last_seen_at`` still advances, so "this posting is still live" stays true.
    """
    now = _now()
    assignments = ", ".join(f"{field} = excluded.{field}" for field in _IMPORT_FIELDS)

    with get_db() as conn:
        for listing in listings:
            conn.execute(
                f"""
                INSERT INTO jobs (
                    id, source, title, company, location, url, description,
                    salary, work_model, match_score, publish_time,
                    publish_time_desc, skills, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    {assignments}
                WHERE jobs.application_status <> 'applied'
                """,
                (
                    listing.id,
                    source,
                    _as_text(listing.title),
                    _as_text(listing.company),
                    _as_text(listing.location),
                    _as_text(listing.url),
                    _as_text(listing.description),
                    _as_text(listing.salary),
                    _as_text(listing.work_model),
                    _as_text(listing.match_score),
                    _as_text(listing.publish_time),
                    _as_text(listing.publish_time_desc),
                    _as_text(listing.skills),
                    now,
                    now,
                ),
            )
            # The guarded upsert above skips applied rows entirely, so touch
            # last_seen_at separately to record that the posting is still live.
            conn.execute(
                "UPDATE jobs SET last_seen_at = ?"
                " WHERE id = ? AND application_status = 'applied'",
                (now, listing.id),
            )
    return list_jobs()


def list_jobs() -> list[dict[str, Any]]:
    """Every stored job. Not-yet-applied first, then most recently seen."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs"
            " ORDER BY application_status = 'applied', last_seen_at DESC, company"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_job(job_id: str) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise JobNotFound(job_id)
    return _row_to_dict(row)


def is_locked(job_id: str) -> bool:
    """True once a job is applied. Cheap enough to call on every pipeline entry."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT application_status FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return row is not None and row["application_status"] == "applied"


def mark_applied(job_id: str) -> dict[str, Any]:
    """Record that this job was applied to, and freeze the row.

    Idempotent rather than an error on repeat: two clicks should not produce a
    failure, and the first application date is the one worth keeping.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT application_status FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        if row["application_status"] != "applied":
            conn.execute(
                "UPDATE jobs SET application_status = 'applied', applied_at = ?"
                " WHERE id = ?",
                (_now(), job_id),
            )
    return get_job(job_id)


def delete_job(job_id: str) -> dict[str, Any]:
    """Remove a job and everything derived from it.

    The extraction and the resume record are meaningless without their job, so
    they go too. Files already written to the output folder are left alone —
    deleting a document someone may have already sent is not this button's
    job — and the caller is told what remains.
    """
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFound(job_id)

        resume = conn.execute(
            "SELECT file_path FROM job_resume WHERE job_id = ?", (job_id,)
        ).fetchone()

        conn.execute("DELETE FROM job_experience WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM job_resume WHERE job_id = ?", (job_id,))
        conn.execute(
            "UPDATE generated_resumes SET job_application_id = NULL"
            " WHERE job_application_id = ?",
            (job_id,),
        )
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    return {
        "deleted": job_id,
        "title": row["title"],
        "company": row["company"],
        # Non-null when a PDF is still sitting in the output folder.
        "orphanedFile": resume["file_path"] if resume else None,
    }
