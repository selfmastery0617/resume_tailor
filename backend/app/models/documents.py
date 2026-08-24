"""Templates and the documents generated from them.

The snapshot columns are the important part and are carried over unchanged from
the SQLite schema: a generated document records the content, style and layout
that produced it, so a later profile or template edit cannot rewrite what a past
PDF was.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import metadata, owned_by, pk_column, timestamps

TEMPLATE_SOURCES = ("builtin", "user")
TEMPLATE_VISIBILITY = ("private", "org")
DOCUMENT_KINDS = ("resume", "cover_letter")

templates = Table(
    "templates",
    metadata,
    pk_column(),
    # Null for the source-controlled built-ins, which belong to nobody.
    Column(
        "org_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column(
        "owner_user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("key", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("source", String(8), nullable=False, server_default=text("'user'")),
    Column("visibility", String(8), nullable=False, server_default=text("'private'")),
    Column("renderer_key", Text, nullable=False, server_default=text("'layout-v1'")),
    Column("current_version", Integer, nullable=False, server_default=text("1")),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    *timestamps(),
    CheckConstraint("source IN ('builtin', 'user')", name="source_known"),
    CheckConstraint("visibility IN ('private', 'org')", name="visibility_known"),
    # A built-in belongs to no org and no user; a user template must have both.
    CheckConstraint(
        "(source = 'builtin') = (org_id IS NULL)", name="builtin_has_no_org"
    ),
)

templates_versions = Table(
    "template_versions",
    metadata,
    pk_column(),
    Column(
        "template_id",
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("version", Integer, nullable=False),
    # Genuinely schemaless: a layout is a tree of positioned blocks.
    Column("layout", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("default_style", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("template_id", "version", name="uq_template_versions_template_id_version"),
)

profile_template_settings = Table(
    "profile_template_settings",
    metadata,
    Column("profile_id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column(
        "template_id",
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("template_version", Integer, nullable=False, server_default=text("1")),
    Column("style_overrides", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    owned_by("profiles", column="profile_id"),
)

generated_documents = Table(
    "generated_documents",
    metadata,
    pk_column(),
    Column("profile_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    # Nullable: a profile can hold a generic resume that no listing prompted.
    Column("job_id", UUID(as_uuid=True), nullable=True),
    Column(
        "run_id",
        UUID(as_uuid=True),
        ForeignKey("extraction_runs.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("kind", String(16), nullable=False, server_default=text("'resume'")),
    Column(
        "template_id",
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("template_version", Integer, nullable=False, server_default=text("1")),
    # Immutable snapshots. This is what makes a document from March still
    # explicable in September.
    Column("content_snapshot", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("style_snapshot", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("layout_snapshot", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("file_name", Text, nullable=False),
    # An object-storage key, not a Windows path: the backend that writes it is
    # not the machine that reads it.
    Column("storage_key", Text, nullable=True),
    Column("byte_size", Integer, nullable=False, server_default=text("0")),
    Column("page_count", Integer, nullable=False, server_default=text("0")),
    Column("content_hash", Text, nullable=False, server_default=text("''")),
    Column("generated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    owned_by("profiles", column="profile_id"),
    # A document cannot be filed against one profile's job while claiming
    # another profile's resume.
    ForeignKeyConstraint(
        ["job_id", "profile_id"], ["jobs.id", "jobs.profile_id"], ondelete="CASCADE"
    ),
    CheckConstraint("kind IN ('resume', 'cover_letter')", name="kind_known"),
)

Index(
    "ix_generated_documents_job",
    generated_documents.c.job_id,
    generated_documents.c.generated_at.desc(),
)

__all__ = [
    "DOCUMENT_KINDS",
    "TEMPLATE_SOURCES",
    "TEMPLATE_VISIBILITY",
    "generated_documents",
    "profile_template_settings",
    "templates",
    "templates_versions",
]
