"""User-created templates (template-builder steps 3-4).

Built-ins live in registry.py as source-controlled code and are never written
here. This module owns only `source = 'user'` rows, and the public lookups in
registry.py merge the two so callers see one catalog.

Every save bumps `version`; generated resumes pin (template_id, version) plus a
layout snapshot, so editing a template cannot alter an already-generated PDF.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import get_db
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
    return TemplateDefinition(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        version=row["version"],
        active=bool(row["active"]),
        rendererKey=row["renderer_key"],
        defaultStyle=json.loads(row["default_style_json"]),
        # A layout template honours every style field; nothing is ignored.
        supportedStyleFields=[],
        source=row["source"],
        layout=json.loads(row["layout_json"]),
        ownerProfileId=row["owner_profile_id"],
    )


def list_user_templates(include_inactive: bool = False) -> list[TemplateDefinition]:
    query = "SELECT * FROM template_definitions WHERE source = 'user'"
    if not include_inactive:
        query += " AND active = 1"
    query += " ORDER BY created_at"
    with get_db() as conn:
        rows = conn.execute(query).fetchall()
    return [_row_to_definition(r) for r in rows]


def get_user_template(template_id: str) -> TemplateDefinition | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM template_definitions WHERE id = ?", (template_id,)
        ).fetchone()
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

    template_id = f"{USER_ID_PREFIX}{uuid.uuid4().hex[:12]}"
    now = _now()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO template_definitions"
            " (id, name, description, version, active, renderer_key, source,"
            "  layout_json, default_style_json, owner_profile_id, created_at, updated_at)"
            " VALUES (?, ?, ?, 1, 1, ?, 'user', ?, ?, ?, ?, ?)",
            (
                template_id,
                clean_name,
                (description or "").strip(),
                LAYOUT_RENDERER_KEY,
                parsed_layout.model_dump_json(),
                json.dumps(style),
                owner_profile_id,
                now,
                now,
            ),
        )
    created = get_user_template(template_id)
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

    with get_db() as conn:
        conn.execute(
            "UPDATE template_definitions SET"
            "  name = ?, description = ?, layout_json = ?, default_style_json = ?,"
            "  active = ?, version = version + 1, updated_at = ?"
            " WHERE id = ?",
            (
                new_name,
                existing.description if description is None else description.strip(),
                json.dumps(new_layout),
                json.dumps(new_style),
                1 if (existing.active if active is None else active) else 0,
                _now(),
                template_id,
            ),
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
        conn.execute("DELETE FROM template_definitions WHERE id = ?", (template_id,))


def layout_for(template: TemplateDefinition) -> dict[str, Any] | None:
    """The layout document to render with, or None for a code renderer."""
    return template.layout or None
