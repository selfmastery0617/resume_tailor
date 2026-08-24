"""Extraction runs: what the pipeline decided, and why.

Replaces the single job_experience JSON blob. A run is auditable — which
product won, which projects were picked, which challenge each bullet came from
— so a surprising resume can be explained months later.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import metadata, pk_column, timestamps

RUN_STATES = ("running", "succeeded", "failed")
ROLE_SLOTS = ("job1", "job2")
GENERATORS = ("deepseek", "chatgpt", "fallback")
SEARCH_MODES = ("semantic", "lexical")

extraction_runs = Table(
    "extraction_runs",
    metadata,
    pk_column(),
    Column(
        "job_id",
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("state", String(16), nullable=False, server_default=text("'running'")),
    # The resume summary written from the bullets, late in the same chat.
    Column("summary", Text, nullable=False, server_default=text("''")),
    # The professional title written for this specific role, after the summary.
    # Named generated_title so it is never confused with the job's own title.
    Column("generated_title", Text, nullable=False, server_default=text("''")),
    # The resume's skill set, written last in the DeepSeek chat, before
    # handoff to ChatGPT. Comma-separated, matching how jobs.skills already
    # stores a skill list elsewhere -- not extraction_skills, which holds
    # skills parsed out of the job description, a different, earlier thing.
    Column("skill_set", Text, nullable=False, server_default=text("''")),
    Column("job_mission", Text, nullable=False, server_default=text("''")),
    # 'fallback' means the provider was unavailable and bullets came straight
    # from the corpus — surfaced rather than passed off as generated.
    Column("generator", String(16), nullable=False, server_default=text("'fallback'")),
    Column("search_mode", String(16), nullable=False, server_default=text("'lexical'")),
    Column("search_model", Text, nullable=False, server_default=text("''")),
    # How many prompts shared this job's single chat. 0 means never connected.
    Column("provider_turns", SmallInteger, nullable=False, server_default=text("0")),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("error", Text, nullable=True),
    CheckConstraint("state IN ('running', 'succeeded', 'failed')", name="state_known"),
    CheckConstraint(
        "generator IN ('deepseek', 'chatgpt', 'fallback')", name="generator_known"
    ),
    CheckConstraint("search_mode IN ('semantic', 'lexical')", name="search_mode_known"),
)

Index("ix_extraction_runs_job", extraction_runs.c.job_id, extraction_runs.c.started_at.desc())

extraction_roles = Table(
    "extraction_roles",
    metadata,
    pk_column(),
    Column(
        "run_id",
        UUID(as_uuid=True),
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("slot", String(8), nullable=False),
    # The chosen company and product as real references rather than copied text.
    # SET NULL, not CASCADE: deleting a company from the corpus must not delete
    # the record of a resume that already went out.
    Column(
        "company_id",
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "product_id",
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    ),
    # Denormalised copies, so a run still reads correctly after corpus edits.
    Column("company_name", Text, nullable=False, server_default=text("''")),
    Column("product_name", Text, nullable=False, server_default=text("''")),
    Column("timeline", Text, nullable=False, server_default=text("''")),
    Column("company_summary", Text, nullable=False, server_default=text("''")),
    # This role's own headline (e.g. "Senior Data Engineer"), written by
    # ChatGPT from just this company's bullets -- see _revise_with_chatgpt in
    # experience_service.py. Rendered on the resume as-is, below the company
    # name (product name is left off for now).
    Column("title", Text, nullable=False, server_default=text("''")),
    UniqueConstraint("run_id", "slot", name="uq_extraction_roles_run_id_slot"),
    CheckConstraint("slot IN ('job1', 'job2')", name="slot_known"),
)

extraction_role_projects = Table(
    "extraction_role_projects",
    metadata,
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("extraction_roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "project_id",
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("project_name", Text, nullable=False, server_default=text("''")),
    Column("best_score", Numeric(6, 4), nullable=True),
)

extraction_bullets = Table(
    "extraction_bullets",
    metadata,
    pk_column(),
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("extraction_roles.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("position", SmallInteger, nullable=False),
    Column("text", Text, nullable=False),
    # Provenance: which challenge this claim came from. The link that makes
    # "where did this number come from" answerable.
    Column(
        "source_challenge_id",
        UUID(as_uuid=True),
        ForeignKey("challenges.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("score", Numeric(6, 4), nullable=True),
    UniqueConstraint("role_id", "position", name="uq_extraction_bullets_role_id_position"),
)

extraction_skills = Table(
    "extraction_skills",
    metadata,
    Column(
        "run_id",
        UUID(as_uuid=True),
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Free text: these are parsed out of a job description, not from the user's
    # own skill list, so they must not be forced to match an existing row.
    Column("name", Text, primary_key=True),
    Column("position", SmallInteger, nullable=False, server_default=text("0")),
)

extraction_events = Table(
    "extraction_events",
    metadata,
    pk_column(),
    Column(
        "run_id",
        UUID(as_uuid=True),
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("seq", Integer, nullable=False),
    Column("level", String(8), nullable=False, server_default=text("'info'")),
    Column("stage", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("data", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("run_id", "seq", name="uq_extraction_events_run_id_seq"),
    CheckConstraint(
        "level IN ('info', 'step', 'result', 'warn', 'error')", name="level_known"
    ),
)

__all__ = [
    "GENERATORS",
    "ROLE_SLOTS",
    "RUN_STATES",
    "SEARCH_MODES",
    "extraction_bullets",
    "extraction_events",
    "extraction_role_projects",
    "extraction_roles",
    "extraction_runs",
    "extraction_skills",
]
