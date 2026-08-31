"""Imported job listings and their application history.

Jobs were never persisted — they lived in React state, which is why
job_experience and job_resume were keyed by an id with no row behind it. These
are the rows everything downstream already assumed existed.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from .base import metadata, owned_by, pk_column, timestamps

# What the application has done. Advances on its own; never hand-edited.
PIPELINE_STATES = ("imported", "extracted", "generated")

# What the user did in the outside world.
#
# 'not_applied' is what the table shows as an empty Status: a row nothing has
# happened to yet. 'ready' is set by the application when a resume exists, and
# is the only value the user can move away from — the table never lets a status
# go back to empty, because "no resume yet" is not something a person chooses.
APPLICATION_STATUSES = (
    "not_applied",
    "ready",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
)

# Statuses that mean an application was actually submitted, and therefore carry
# a date. Kept beside the CHECK below so the two cannot drift.
APPLIED_STATUSES = ("applied", "interviewing", "offer", "rejected", "withdrawn")

APPLICATION_EVENT_KINDS = (
    "applied",
    "acknowledged",
    "screen",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
    "note",
)

import_batches = Table(
    "import_batches",
    metadata,
    pk_column(),
    Column("profile_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("source", Text, nullable=False, server_default=text("'jobright'")),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("row_count", Integer, nullable=False, server_default=text("0")),
    Column("error", Text, nullable=True),
    owned_by("profiles", column="profile_id"),
)

jobs = Table(
    "jobs",
    metadata,
    pk_column(),
    # Which resume identity is chasing this role.
    Column("profile_id", UUID(as_uuid=True), nullable=False),
    # Denormalised for row-level security; held consistent by the composite key.
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column(
        "import_batch_id",
        UUID(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("source", Text, nullable=False, server_default=text("'jobright'")),
    # Jobright's own id. Kept for re-import matching; never a primary key.
    Column("source_job_id", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("company", Text, nullable=False, server_default=text("''")),
    Column("location", Text, nullable=False, server_default=text("''")),
    Column("url", Text, nullable=False, server_default=text("''")),
    # A direct posting link supplied by the user. This is intentionally
    # separate from the imported/source URL: DeepSeek uses it to fetch the
    # description, while re-importing a row may continue to refresh `url`.
    Column("job_url", Text, nullable=False, server_default=text("''")),
    # The full description, not the summary. Postgres stores large values out of
    # line automatically, so there is no size concern here.
    Column("description", Text, nullable=False, server_default=text("''")),
    # Verbatim, because the source text is inconsistent...
    Column("salary_raw", Text, nullable=False, server_default=text("''")),
    # ...and parsed where possible, so the column can be sorted and filtered.
    Column("salary_min", Numeric(12, 2), nullable=True),
    Column("salary_max", Numeric(12, 2), nullable=True),
    Column("work_model", Text, nullable=False, server_default=text("''")),
    # The source's own skill tags for the listing, kept verbatim. Distinct from
    # extraction_skills, which is what the model parsed out of the description.
    Column("skills", Text, nullable=False, server_default=text("''")),
    # Arrives from Jobright as a string; a number is sortable.
    Column("match_score", Numeric(5, 2), nullable=True),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column(
        "pipeline_state",
        String(16),
        nullable=False,
        server_default=text("'imported'"),
    ),
    Column(
        "application_status",
        String(16),
        nullable=False,
        server_default=text("'not_applied'"),
    ),
    Column("applied_at", DateTime(timezone=True), nullable=True),
    # The date the job was added. Editable, and auto-stamped on first edit of a
    # row that has none, so a hand-typed row still records when it appeared.
    # A date rather than a timestamp: nobody edits the minute they added a job.
    Column("date_added", Date, nullable=True),
    # Which PDF was actually sent. Regenerating later must not rewrite history,
    # so this pins the document as it was at the moment of applying.
    Column("applied_document_id", UUID(as_uuid=True), nullable=True),
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    # Soft dismiss: hiding a job must not delete its extraction history.
    Column("archived_at", DateTime(timezone=True), nullable=True),
    Column("notes", Text, nullable=False, server_default=text("''")),
    *timestamps(),
    owned_by("profiles", column="profile_id"),
    # Re-importing updates rather than duplicates. Scoped to the profile, so the
    # same listing can be tracked under two identities.
    UniqueConstraint(
        "profile_id", "source", "source_job_id",
        name="uq_jobs_profile_id_source_source_job_id",
    ),
    UniqueConstraint("id", "profile_id", name="uq_jobs_id_profile_id"),
    CheckConstraint(
        "pipeline_state IN ('imported', 'extracted', 'generated')",
        name="pipeline_state_known",
    ),
    CheckConstraint(
        "application_status IN ('not_applied', 'ready', 'applied',"
        " 'interviewing', 'offer', 'rejected', 'withdrawn')",
        name="application_status_known",
    ),
    # You cannot be interviewing somewhere you never applied, and you cannot
    # have applied without a date. One constraint, both directions.
    #
    # Written as "did they apply" rather than "is it not_applied" because there
    # are now two states that precede applying: nothing yet, and ready to send.
    CheckConstraint(
        "(application_status IN ('applied', 'interviewing', 'offer', 'rejected',"
        " 'withdrawn')) = (applied_at IS NOT NULL)",
        name="applied_at_matches_status",
    ),
    CheckConstraint(
        "salary_max IS NULL OR salary_min IS NULL OR salary_max >= salary_min",
        name="salary_ordered",
    ),
)

# The list actually worked from: not yet applied, newest first.
Index(
    "ix_jobs_todo",
    jobs.c.profile_id,
    jobs.c.first_seen_at.desc(),
    postgresql_where=text(
        "application_status IN ('not_applied', 'ready') AND archived_at IS NULL"
    ),
)

Index("ix_jobs_profile_status", jobs.c.profile_id, jobs.c.application_status)

application_events = Table(
    "application_events",
    metadata,
    pk_column(),
    Column(
        "job_id",
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", String(16), nullable=False),
    # When it happened, not when it was recorded — those differ often enough
    # that measuring response time from created_at would be wrong.
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    # Which resume was sent, for an "applied" event.
    Column("document_id", UUID(as_uuid=True), nullable=True),
    Column("note", Text, nullable=False, server_default=text("''")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "kind IN ('applied', 'acknowledged', 'screen', 'interview', 'offer',"
        " 'rejected', 'withdrawn', 'note')",
        name="kind_known",
    ),
)

Index(
    "ix_application_events_job_occurred",
    application_events.c.job_id,
    application_events.c.occurred_at.desc(),
)

__all__ = [
    "APPLIED_STATUSES",
    "APPLICATION_EVENT_KINDS",
    "APPLICATION_STATUSES",
    "PIPELINE_STATES",
    "application_events",
    "import_batches",
    "jobs",
]
