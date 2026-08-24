"""Organizations, users, membership and the audit trail.

An organization layer costs four columns now and a rewrite later. With one team
there is exactly one row, but a second team becomes an insert rather than a
migration.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import metadata, pk_column, timestamps

ROLES = ("owner", "admin", "member")
USER_STATUSES = ("invited", "active", "suspended")

organizations = Table(
    "organizations",
    metadata,
    pk_column(),
    Column("name", Text, nullable=False),
    Column("slug", Text, nullable=False, unique=True),
    *timestamps(),
)

users = Table(
    "users",
    metadata,
    pk_column(),
    # citext would be tidier, but it needs an extension; a lowercase generated
    # column is portable and does the same job. See the unique index below.
    Column("email", Text, nullable=False),
    Column("full_name", Text, nullable=False, server_default=text("''")),
    # Null when the user signs in through an external identity provider.
    Column("password_hash", Text, nullable=True),
    Column(
        "status",
        String(16),
        nullable=False,
        server_default=text("'invited'"),
    ),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
    *timestamps(),
    CheckConstraint(
        "status IN ('invited', 'active', 'suspended')",
        name="status_known",
    ),
)

# "Alex@Example.com" and "alex@example.com" are the same account.
# Expressed through users.c.email rather than text("lower(email)"): an Index
# built only from a text fragment has no table to bind to, so it is silently
# never created.
Index("ix_users_email_lower", func.lower(users.c.email), unique=True)

memberships = Table(
    "memberships",
    metadata,
    pk_column(),
    Column(
        "org_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("role", String(16), nullable=False, server_default=text("'member'")),
    Column("joined_at", DateTime(timezone=True), nullable=True),
    Column(
        "invited_by",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    *timestamps(),
    UniqueConstraint("org_id", "user_id", name="uq_memberships_org_id_user_id"),
    CheckConstraint("role IN ('owner', 'admin', 'member')", name="role_known"),
)

invitations = Table(
    "invitations",
    metadata,
    pk_column(),
    Column(
        "org_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("email", Text, nullable=False),
    Column("role", String(16), nullable=False, server_default=text("'member'")),
    # The token itself is shown once and never stored; only its hash lives here,
    # so a database leak does not hand out working invitations.
    Column("token_hash", Text, nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    Column(
        "invited_by",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    *timestamps(),
    CheckConstraint("role IN ('owner', 'admin', 'member')", name="role_known"),
)

Index(
    "ix_invitations_pending",
    invitations.c.org_id,
    invitations.c.email,
    unique=True,
    postgresql_where=text("accepted_at IS NULL"),
)

sessions = Table(
    "sessions",
    metadata,
    pk_column(),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    # Set on sign-out, so a session can be ended server-side rather than
    # relying on the client to forget its token.
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("user_agent", Text, nullable=False, server_default=text("''")),
    Column("ip", Text, nullable=False, server_default=text("''")),
    *timestamps(),
)

Index(
    "ix_sessions_user_active",
    sessions.c.user_id,
    postgresql_where=text("revoked_at IS NULL"),
)

audit_log = Table(
    "audit_log",
    metadata,
    pk_column(),
    Column(
        "org_id",
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Kept when the actor is deleted: an audit row that loses its subject is
    # worse than useless, so the id goes null and the description remains.
    Column(
        "actor_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("action", Text, nullable=False),
    Column("subject_type", Text, nullable=False, server_default=text("''")),
    Column("subject_id", UUID(as_uuid=True), nullable=True),
    Column("detail", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("occurred_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

Index("ix_audit_log_org_occurred", audit_log.c.org_id, audit_log.c.occurred_at.desc())

__all__ = [
    "ROLES",
    "USER_STATUSES",
    "audit_log",
    "invitations",
    "memberships",
    "organizations",
    "sessions",
    "users",
]
