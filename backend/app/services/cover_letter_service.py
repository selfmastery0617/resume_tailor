"""Per-profile cover letter template selection and style overrides.

Mirrors profile_service.py's template-settings functions
(get_template_settings/save_template_settings/reset_template_settings), but
simpler: a cover letter template has no DB row of its own to resolve (see
app/services/cover_letter_templates/registry.py's docstring) -- template_id
is stored as the registry key directly (plain text), not a UUID FK.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select

from app.db import get_db
from app.models import profile_cover_letter_settings, profiles
from app.schemas.cover_letter_style import merge_cover_letter_style, validate_cover_letter_overrides
from app.schemas.cover_letter_template import ProfileCoverLetterTemplateSettings
from app.services.cover_letter_templates.registry import (
    DEFAULT_COVER_LETTER_TEMPLATE_ID,
    get_cover_letter_template,
    resolve_cover_letter_template,
)
# Reused, not redeclared: a router catching profile_service.ProfileNotFound
# for the resume template-settings endpoints must catch the same exception
# here too, not a same-named-but-distinct class the except clause would
# silently fail to match.
from app.services.profile_service import ProfileNotFound


class CoverLetterTemplateNotFound(LookupError):
    """No cover letter template with this id."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ProfileNotFound(str(value)) from exc


def _effective_style(template_id: str, overrides: dict) -> dict:
    template = resolve_cover_letter_template(template_id)
    return merge_cover_letter_style(template.defaultStyle, overrides).model_dump()


def get_cover_letter_template_settings(profile_id: str) -> ProfileCoverLetterTemplateSettings:
    target = _as_uuid(profile_id)
    with get_db() as conn:
        if conn.execute(select(profiles.c.id).where(profiles.c.id == target)).scalar() is None:
            raise ProfileNotFound(profile_id)

        row = conn.execute(
            select(profile_cover_letter_settings).where(
                profile_cover_letter_settings.c.profile_id == target
            )
        ).first()

        if row is None:
            # Profile predates its settings row, or they were reset.
            return ProfileCoverLetterTemplateSettings(
                profileId=profile_id,
                templateId=DEFAULT_COVER_LETTER_TEMPLATE_ID,
                styleOverrides={},
                effectiveStyle=_effective_style(DEFAULT_COVER_LETTER_TEMPLATE_ID, {}),
                updatedAt=_now(),
            )

        overrides = row.style_overrides or {}
        return ProfileCoverLetterTemplateSettings(
            profileId=profile_id,
            templateId=row.template_id,
            styleOverrides=overrides,
            effectiveStyle=_effective_style(row.template_id, overrides),
            updatedAt=row.updated_at.isoformat().replace("+00:00", "Z"),
        )


def save_cover_letter_template_settings(
    profile_id: str, template_id: str, style_overrides: dict
) -> ProfileCoverLetterTemplateSettings:
    target = _as_uuid(profile_id)

    if get_cover_letter_template(template_id) is None:
        raise CoverLetterTemplateNotFound(template_id)

    cleaned = validate_cover_letter_overrides(style_overrides)

    with get_db() as conn:
        row = conn.execute(select(profiles.c.user_id).where(profiles.c.id == target)).first()
        if row is None:
            raise ProfileNotFound(profile_id)

        values = {
            "profile_id": target,
            "user_id": row.user_id,
            "template_id": template_id,
            "style_overrides": cleaned,
        }
        existing = conn.execute(
            select(profile_cover_letter_settings.c.profile_id).where(
                profile_cover_letter_settings.c.profile_id == target
            )
        ).scalar()
        if existing is None:
            conn.execute(profile_cover_letter_settings.insert().values(**values))
        else:
            conn.execute(
                profile_cover_letter_settings.update()
                .where(profile_cover_letter_settings.c.profile_id == target)
                .values(**values, updated_at=func.now())
            )

    return get_cover_letter_template_settings(profile_id)


def reset_cover_letter_template_settings(profile_id: str) -> ProfileCoverLetterTemplateSettings:
    """Drop overrides and return to the default template. Content is untouched."""
    return save_cover_letter_template_settings(profile_id, DEFAULT_COVER_LETTER_TEMPLATE_ID, {})
