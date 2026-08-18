"""User-created templates (template-builder steps 3-4).

Built-ins live in registry.py as source-controlled code and are never written
here. This module owns only `source = 'user'` rows, and the public lookups in
registry.py merge the two so callers see one catalog.

Every save bumps `version`; generated resumes pin (template_id, version) plus a
layout snapshot, so editing a template cannot alter an already-generated PDF.
"""

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, delete, func, select

from app.bootstrap import current_org_id, current_user_id
from app.db import get_db
from app.ids import uuid7
from app.models import templates, templates_versions
from app.schemas.layout import LayoutError, default_layout, validate_layout
from app.schemas.style import validate_overrides
from app.schemas.template import TemplateDefinition

LAYOUT_RENDERER_KEY = "layout-v1"

# Distinct prefix so a user template can never collide with `template-N`.
USER_ID_PREFIX = "user-template-"


class TemplateNotFound(LookupError):
    pass


class TemplateReadOnly(PermissionError):
    """Raised when a caller tries to modify a source-controlled built-in."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _row_to_definition(row) -> TemplateDefinition:
    """Row pair (templates joined to its current template_versions) -> schema.

    The app knows a template by its key ("user-template-ab12"); the database
    knows it by a UUID. `key` is what crosses the boundary, so nothing above
    this module had to change.
    """
    return TemplateDefinition(
        id=row.key,
        name=row.name,
        description=row.description,
        version=row.current_version,
        active=bool(row.is_active),
        rendererKey=row.renderer_key,
        defaultStyle=row.default_style or {},
        # A layout template honours every style field; nothing is ignored.
        supportedStyleFields=[],
        source=row.source,
        layout=row.layout or {},
        ownerProfileId=None,
    )


def _with_current_version():
    """templates joined to the template_versions row it currently points at."""
    return (
        select(
            templates.c.key,
            templates.c.name,
            templates.c.description,
            templates.c.source,
            templates.c.renderer_key,
            templates.c.current_version,
            templates.c.is_active,
            templates.c.created_at,
            templates_versions.c.layout,
            templates_versions.c.default_style,
        )
        .select_from(
            templates.join(
                templates_versions,
                (templates_versions.c.template_id == templates.c.id)
                & (templates_versions.c.version == templates.c.current_version),
            )
        )
    )


def list_user_templates(include_inactive: bool = False) -> list[TemplateDefinition]:
    query = _with_current_version().where(templates.c.source == "user")
    if not include_inactive:
        query = query.where(templates.c.is_active.is_(True))
    with get_db() as conn:
        rows = conn.execute(query.order_by(templates.c.created_at)).all()
    return [_row_to_definition(r) for r in rows]


def get_user_template(template_id: str) -> TemplateDefinition | None:
    with get_db() as conn:
        row = conn.execute(
            _with_current_version().where(templates.c.key == template_id)
        ).first()
    return _row_to_definition(row) if row else None


def create_user_template(
    name: str,
    description: str = "",
    layout: dict | None = None,
    default_style: dict | None = None,
    owner_profile_id: str | None = None,
) -> TemplateDefinition:
    """Create a template. With no layout, starts from the default document."""
    parsed_layout = (
        validate_layout(layout) if layout is not None else default_layout()
    )
    style = validate_overrides(default_style)

    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Template name is required")

    template_key = f"{USER_ID_PREFIX}{uuid.uuid4().hex[:12]}"
    with get_db() as conn:
        row_id = conn.execute(
            templates.insert()
            .values(
                id=uuid7(),
                org_id=current_org_id(),
                owner_user_id=current_user_id(),
                key=template_key,
                name=clean_name,
                description=(description or "").strip(),
                source="user",
                visibility="private",
                renderer_key=LAYOUT_RENDERER_KEY,
                current_version=1,
                is_active=True,
            )
            .returning(templates.c.id)
        ).scalar_one()
        # The layout and style live on the version row, so an edit can bump the
        # version without overwriting what a generated resume was rendered from.
        conn.execute(
            templates_versions.insert().values(
                id=uuid7(),
                template_id=row_id,
                version=1,
                layout=parsed_layout.model_dump(),
                default_style=style,
            )
        )
    created = get_user_template(template_key)
    assert created is not None
    return created


def duplicate_template(
    source_template: TemplateDefinition,
    name: str | None = None,
    layout: dict | None = None,
) -> TemplateDefinition:
    """Copy any template — built-in or user — into a new editable one.

    This is how a built-in becomes customisable without its source file ever
    being written to.
    """
    return create_user_template(
        name=name or f"{source_template.name} (copy)",
        description=source_template.description,
        # A built-in has no layout document, so the caller supplies the
        # equivalent one; otherwise reuse the source's own layout.
        layout=layout if layout is not None else (source_template.layout or None),
        default_style=dict(source_template.defaultStyle),
    )


def _assert_editable(template_id: str) -> TemplateDefinition:
    """Fetch a user template, distinguishing 'read-only' from 'missing'.

    A built-in exists but cannot be written, so reporting it as not-found would
    send the caller looking for the wrong problem.
    """
    if _is_builtin(template_id):
        raise TemplateReadOnly(template_id)

    existing = get_user_template(template_id)
    if existing is None:
        raise TemplateNotFound(template_id)
    if existing.source != "user":
        raise TemplateReadOnly(template_id)
    return existing


def _is_builtin(template_id: str) -> bool:
    # Imported lazily; registry imports this module's package.
    from app.services.templates.registry import list_builtin_templates

    return any(t.id == template_id for t in list_builtin_templates(include_inactive=True))


def update_user_template(
    template_id: str,
    name: str | None = None,
    description: str | None = None,
    layout: dict | None = None,
    default_style: dict | None = None,
    active: bool | None = None,
) -> TemplateDefinition:
    existing = _assert_editable(template_id)

    new_layout = existing.layout
    if layout is not None:
        new_layout = validate_layout(layout).model_dump()

    new_style = existing.defaultStyle
    if default_style is not None:
        new_style = validate_overrides(default_style)

    new_name = existing.name if name is None else (name or "").strip()
    if not new_name:
        raise ValueError("Template name is required")

    next_version = existing.version + 1
    with get_db() as conn:
        row_id = conn.execute(
            select(templates.c.id).where(templates.c.key == template_id)
        ).scalar_one()
        conn.execute(
            templates.update()
            .where(templates.c.id == row_id)
            .values(
                name=new_name,
                description=(
                    existing.description if description is None else description.strip()
                ),
                is_active=existing.active if active is None else active,
                current_version=next_version,
                updated_at=func.now(),
            )
        )
        # A new row rather than an update: past versions stay readable, which is
        # what lets a generated resume be explained after the template moves on.
        conn.execute(
            templates_versions.insert().values(
                id=uuid7(),
                template_id=row_id,
                version=next_version,
                layout=new_layout,
                default_style=new_style,
            )
        )
    updated = get_user_template(template_id)
    assert updated is not None
    return updated


def delete_user_template(template_id: str) -> None:
    """Remove a user template.

    Profiles still pointing at it fall back to the default template on next
    resolve (TM-FR-004), and generated resumes keep their layout snapshot, so
    deleting never corrupts history.
    """
    _assert_editable(template_id)
    with get_db() as conn:
        conn.execute(delete(templates).where(templates.c.key == template_id))


def layout_for(template: TemplateDefinition) -> dict[str, Any] | None:
    """The layout document to render with, or None for a code renderer."""
    return template.layout or None
