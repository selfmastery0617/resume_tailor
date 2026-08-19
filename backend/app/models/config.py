"""Settings, prompts, provider accounts and the work queue.

Settings and prompts resolve most-specific-first: profile beats user beats org
beats the shipped default. That replaces a single global key/value table where
one person editing the tailoring prompt edited it for everyone.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import metadata, pk_column, timestamps

SETTING_SCOPES = ("org", "user", "profile")
PROMPT_KINDS = ("skills", "tailoring", "summary", "title", "corpus")
PROVIDERS = ("deepseek", "chatgpt", "jobright")
PROVIDER_STATUSES = ("disconnected", "connected", "expired", "error")
QUEUE_STATES = ("queued", "running", "succeeded", "failed", "cancelled")

settings = Table(
    "settings",
    metadata,
    pk_column(),
    Column("scope", String(8), nullable=False),
    # Exactly one of these is set, matching `scope`.
    Column("org_id", UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
    Column("profile_id", UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True),
    Column("key", Text, nullable=False),
    Column("value", JSONB, nullable=False),
    *timestamps(),
    CheckConstraint("scope IN ('org', 'user', 'profile')", name="scope_known"),
    # The owner column must match the declared scope; anything else is a row
    # that resolution would silently skip.
    CheckConstraint(
        "(scope = 'org'     AND org_id IS NOT NULL AND user_id IS NULL     AND profile_id IS NULL) OR"
        "(scope = 'user'    AND user_id IS NOT NULL AND org_id IS NULL     AND profile_id IS NULL) OR"
        "(scope = 'profile' AND profile_id IS NOT NULL AND org_id IS NULL  AND user_id IS NULL)",
        name="owner_matches_scope",
    ),
)

# One row per key per owner, per scope.
Index("ix_settings_org_key", settings.c.org_id, settings.c.key, unique=True,
      postgresql_where=text("scope = 'org'"))
Index("ix_settings_user_key", settings.c.user_id, settings.c.key, unique=True,
      postgresql_where=text("scope = 'user'"))
Index("ix_settings_profile_key", settings.c.profile_id, settings.c.key, unique=True,
      postgresql_where=text("scope = 'profile'"))

prompts = Table(
    "prompts",
    metadata,
    pk_column(),
    Column("scope", String(8), nullable=False),
    Column("org_id", UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
    Column("profile_id", UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True),
    Column("kind", String(16), nullable=False),
    Column("body", Text, nullable=False),
    *timestamps(),
    CheckConstraint("scope IN ('org', 'user', 'profile')", name="scope_known"),
    CheckConstraint(
        "kind IN ('skills', 'tailoring', 'summary', 'title', 'corpus')",
        name="kind_known",
    ),
    CheckConstraint(
        "(scope = 'org'     AND org_id IS NOT NULL AND user_id IS NULL     AND profile_id IS NULL) OR"
        "(scope = 'user'    AND user_id IS NOT NULL AND org_id IS NULL     AND profile_id IS NULL) OR"
        "(scope = 'profile' AND profile_id IS NOT NULL AND org_id IS NULL  AND user_id IS NULL)",
        name="owner_matches_scope",
    ),
)

Index("ix_prompts_org_kind", prompts.c.org_id, prompts.c.kind, unique=True,
      postgresql_where=text("scope = 'org'"))
Index("ix_prompts_user_kind", prompts.c.user_id, prompts.c.kind, unique=True,
      postgresql_where=text("scope = 'user'"))
Index("ix_prompts_profile_kind", prompts.c.profile_id, prompts.c.kind, unique=True,
      postgresql_where=text("scope = 'profile'"))

provider_accounts = Table(
    "provider_accounts",
    metadata,
    pk_column(),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("provider", String(16), nullable=False),
    Column("label", Text, nullable=False, server_default=text("''")),
    # Where this user's browser profile lives. Per user, so eight people do not
    # share one Chromium profile behind one lock.
    Column("profile_ref", Text, nullable=False, server_default=text("''")),
    Column("status", String(16), nullable=False, server_default=text("'disconnected'")),
    Column("last_verified_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
    *timestamps(),
    UniqueConstraint("user_id", "provider", name="uq_provider_accounts_user_id_provider"),
    CheckConstraint(
        "provider IN ('deepseek', 'chatgpt', 'jobright')", name="provider_known"
    ),
    CheckConstraint(
        "status IN ('disconnected', 'connected', 'expired', 'error')",
        name="status_known",
    ),
)

work_queue = Table(
    "work_queue",
    metadata,
    pk_column(),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("job_id", UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True),
    Column("kind", Text, nullable=False, server_default=text("'extract'")),
    Column("state", String(16), nullable=False, server_default=text("'queued'")),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("max_attempts", SmallInteger, nullable=False, server_default=text("3")),
    # Claimed with SELECT ... FOR UPDATE SKIP LOCKED, so several workers can
    # drain the queue without handing the same job to two of them.
    Column("locked_by", Text, nullable=True),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("run_after", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_error", Text, nullable=True),
    *timestamps(),
    CheckConstraint(
        "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
        name="state_known",
    ),
)

# One extraction at a time per user: the provider session cannot be shared, so
# queueing per account is what replaces the global lock.
Index(
    "ix_work_queue_one_running_per_user",
    work_queue.c.user_id,
    unique=True,
    postgresql_where=text("state = 'running'"),
)

Index(
    "ix_work_queue_claimable",
    work_queue.c.run_after,
    postgresql_where=text("state = 'queued'"),
)

__all__ = [
    "PROMPT_KINDS",
    "PROVIDERS",
    "PROVIDER_STATUSES",
    "QUEUE_STATES",
    "SETTING_SCOPES",
    "prompts",
    "provider_accounts",
    "settings",
    "work_queue",
]
