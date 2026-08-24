"""The single implicit account, until real authentication exists.

Every row in the new schema has an owner, but the application has no sign-in
yet. Rather than making ownership nullable — which would have to be undone the
moment accounts arrive — there is one organization and one user, and everything
belongs to them. Adding authentication later means creating real users beside
this one, not changing a single column definition.

Also syncs the source-controlled built-in templates into the templates table.
They live in registry.py as code, but `profile_template_settings.template_id`
is a real foreign key now, so a row has to exist for each.
"""

from __future__ import annotations

import os
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Connection, select

from app.db import get_db
from app.ids import uuid7
from app.models import memberships, organizations, templates, templates_versions, users

DEFAULT_ORG_SLUG = "default"
DEFAULT_ORG_NAME = "JobTailor"
# Overridable so the account carries a real address once someone signs in.
DEFAULT_USER_EMAIL = os.getenv("JOBTAILOR_OWNER_EMAIL", "owner@localhost")


def _ensure_org(conn: Connection) -> UUID:
    found = conn.execute(
        select(organizations.c.id).where(organizations.c.slug == DEFAULT_ORG_SLUG)
    ).scalar()
    if found:
        return found
    return conn.execute(
        organizations.insert()
        .values(id=uuid7(), name=DEFAULT_ORG_NAME, slug=DEFAULT_ORG_SLUG)
        .returning(organizations.c.id)
    ).scalar_one()


def _ensure_user(conn: Connection, org_id: UUID) -> UUID:
    found = conn.execute(
        select(users.c.id).order_by(users.c.created_at).limit(1)
    ).scalar()
    if not found:
        found = conn.execute(
            users.insert()
            .values(id=uuid7(), email=DEFAULT_USER_EMAIL, full_name="", status="active")
            .returning(users.c.id)
        ).scalar_one()

    member = conn.execute(
        select(memberships.c.id).where(
            memberships.c.org_id == org_id, memberships.c.user_id == found
        )
    ).scalar()
    if not member:
        conn.execute(
            memberships.insert().values(
                id=uuid7(), org_id=org_id, user_id=found, role="owner"
            )
        )
    return found


def sync_builtin_templates(conn: Connection) -> int:
    """Give every source-controlled built-in a row, so it can be referenced.

    Built-ins stay defined in code — this only mirrors their identity and
    current definition into the database. A built-in's row carries no org, which
    is what the templates CHECK constraint expects.
    """
    from app.services.templates.registry import list_builtin_templates

    written = 0
    for builtin in list_builtin_templates(include_inactive=True):
        existing = conn.execute(
            select(templates.c.id, templates.c.current_version).where(
                templates.c.key == builtin.id
            )
        ).first()

        if existing is None:
            template_id = conn.execute(
                templates.insert()
                .values(
                    id=uuid7(),
                    org_id=None,
                    owner_user_id=None,
                    key=builtin.id,
                    name=builtin.name,
                    description=builtin.description,
                    source="builtin",
                    visibility="org",
                    renderer_key=builtin.rendererKey,
                    current_version=builtin.version,
                    is_active=builtin.active,
                )
                .returning(templates.c.id)
            ).scalar_one()
            written += 1
        else:
            template_id, _ = existing
            conn.execute(
                templates.update()
                .where(templates.c.id == template_id)
                .values(
                    name=builtin.name,
                    description=builtin.description,
                    current_version=builtin.version,
                    is_active=builtin.active,
                )
            )

        has_version = conn.execute(
            select(templates_versions.c.id).where(
                templates_versions.c.template_id == template_id,
                templates_versions.c.version == builtin.version,
            )
        ).scalar()
        if not has_version:
            conn.execute(
                templates_versions.insert().values(
                    id=uuid7(),
                    template_id=template_id,
                    version=builtin.version,
                    layout=builtin.layout or {},
                    default_style=builtin.defaultStyle or {},
                )
            )
    return written


def ensure_bootstrap() -> tuple[UUID, UUID]:
    """Create the org, the user and the built-in template rows. Idempotent."""
    with get_db() as conn:
        org_id = _ensure_org(conn)
        user_id = _ensure_user(conn, org_id)
        sync_builtin_templates(conn)
    return org_id, user_id


@lru_cache(maxsize=1)
def _cached_ids() -> tuple[UUID, UUID]:
    return ensure_bootstrap()


def current_org_id() -> UUID:
    return _cached_ids()[0]


def current_user_id() -> UUID:
    """Who owns the rows this request writes.

    One account for now. When sign-in lands this reads from the request context
    instead, and every caller below stays as it is.
    """
    return _cached_ids()[1]


def reset_cache() -> None:
    """Forget the memoised ids — used by tests and by the migration script."""
    _cached_ids.cache_clear()
