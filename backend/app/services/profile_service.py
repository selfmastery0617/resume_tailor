"""Profile CRUD and per-profile template settings."""

import json
import uuid
from datetime import datetime, timezone

from app.db import get_db
from app.schemas.resume import Profile, ProfileCreate, ProfileUpdate, ResumeData
from app.schemas.style import merge_style, validate_overrides
from app.schemas.template import ProfileTemplateSettings
from app.services.templates.registry import DEFAULT_TEMPLATE_ID, get_template, resolve_template


class ProfileNotFound(LookupError):
    pass


class TemplateNotFound(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _row_to_profile(row) -> Profile:
    return Profile(
        id=row["id"],
        name=row["name"],
        data=ResumeData(**json.loads(row["data_json"])),
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


# -- profiles -------------------------------------------------------------


def list_profiles() -> list[Profile]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM profiles ORDER BY created_at").fetchall()
    return [_row_to_profile(r) for r in rows]


def get_profile(profile_id: str) -> Profile:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if row is None:
        raise ProfileNotFound(profile_id)
    return _row_to_profile(row)


def create_profile(payload: ProfileCreate) -> Profile:
    profile_id = f"profile-{uuid.uuid4().hex[:12]}"
    now = _now()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO profiles (id, name, data_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (profile_id, payload.name, payload.data.model_dump_json(), now, now),
        )
        # TM-FR-010: new profiles start on template-1.
        conn.execute(
            "INSERT INTO profile_template_settings"
            " (profile_id, template_id, template_version, style_overrides_json, updated_at)"
            " VALUES (?, ?, ?, '{}', ?)",
            (profile_id, DEFAULT_TEMPLATE_ID, 1, now),
        )
    return get_profile(profile_id)


def update_profile(profile_id: str, payload: ProfileUpdate) -> Profile:
    existing = get_profile(profile_id)
    name = payload.name if payload.name is not None else existing.name
    data = payload.data if payload.data is not None else existing.data
    with get_db() as conn:
        conn.execute(
            "UPDATE profiles SET name = ?, data_json = ?, updated_at = ? WHERE id = ?",
            (name, data.model_dump_json(), _now(), profile_id),
        )
    return get_profile(profile_id)


def delete_profile(profile_id: str) -> None:
    get_profile(profile_id)  # raises if missing
    with get_db() as conn:
        # Template settings cascade; generated_resumes keep their snapshots.
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))


# -- template settings ----------------------------------------------------


def _effective_style(template_id: str, overrides: dict) -> dict:
    template = resolve_template(template_id)
    return merge_style(template.defaultStyle, overrides).model_dump()


def get_template_settings(profile_id: str) -> ProfileTemplateSettings:
    get_profile(profile_id)  # 404 when the profile is gone
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM profile_template_settings WHERE profile_id = ?", (profile_id,)
        ).fetchone()

    if row is None:
        # Profile predates settings (or they were reset): report defaults.
        return ProfileTemplateSettings(
            profileId=profile_id,
            templateId=DEFAULT_TEMPLATE_ID,
            templateVersion=1,
            styleOverrides={},
            effectiveStyle=_effective_style(DEFAULT_TEMPLATE_ID, {}),
            updatedAt=_now(),
        )

    overrides = json.loads(row["style_overrides_json"])
    return ProfileTemplateSettings(
        profileId=profile_id,
        templateId=row["template_id"],
        templateVersion=row["template_version"],
        styleOverrides=overrides,
        effectiveStyle=_effective_style(row["template_id"], overrides),
        updatedAt=row["updated_at"],
    )


def save_template_settings(
    profile_id: str, template_id: str, style_overrides: dict
) -> ProfileTemplateSettings:
    get_profile(profile_id)

    template = get_template(template_id)
    if template is None:
        raise TemplateNotFound(template_id)
    if not template.active:
        # Inactive templates stay resolvable for history but can't be chosen anew.
        raise TemplateNotFound(f"{template_id} is not active")

    cleaned = validate_overrides(style_overrides)
    now = _now()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO profile_template_settings"
            " (profile_id, template_id, template_version, style_overrides_json, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(profile_id) DO UPDATE SET"
            "   template_id = excluded.template_id,"
            "   template_version = excluded.template_version,"
            "   style_overrides_json = excluded.style_overrides_json,"
            "   updated_at = excluded.updated_at",
            (profile_id, template.id, template.version, json.dumps(cleaned), now),
        )
    return get_template_settings(profile_id)


def reset_template_settings(profile_id: str) -> ProfileTemplateSettings:
    """Drop overrides and return to the default template (7.5).

    Resume content is untouched.
    """
    get_profile(profile_id)
    now = _now()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO profile_template_settings"
            " (profile_id, template_id, template_version, style_overrides_json, updated_at)"
            " VALUES (?, ?, 1, '{}', ?)"
            " ON CONFLICT(profile_id) DO UPDATE SET"
            "   template_id = excluded.template_id,"
            "   template_version = excluded.template_version,"
            "   style_overrides_json = '{}',"
            "   updated_at = excluded.updated_at",
            (profile_id, DEFAULT_TEMPLATE_ID, now),
        )
    return get_template_settings(profile_id)
