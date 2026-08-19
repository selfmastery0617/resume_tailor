"""Profile CRUD and per-profile template settings.

The resume content that used to sit in one `data_json` column is now four
tables. `ResumeData` is still the shape every caller sees, so this module owns
the translation: assemble it on read, replace the child rows on write.

Ids are UUIDs in the database and strings in the API, because the schemas and
the frontend have always treated them as opaque text.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, delete, func, select

from app.bootstrap import current_user_id
from app.db import get_db
from app.ids import uuid7
from app.models import (
    extraction_roles,
    profile_educations,
    profile_experiences,
    profile_skills,
    profile_template_settings,
    profiles,
    templates,
)
from app.schemas.resume import (
    Education,
    Experience,
    Profile,
    ProfileCreate,
    ProfileInfo,
    ProfileUpdate,
    ResumeData,
    Skill,
)
from app.schemas.style import merge_style, validate_overrides
from app.schemas.template import ProfileTemplateSettings
from app.services.templates.registry import DEFAULT_TEMPLATE_ID, get_template, resolve_template


class ProfileNotFound(LookupError):
    pass


class TemplateNotFound(LookupError):
    pass


# ProfileInfo is camelCase; the columns are snake_case. Listed once here so a
# field added to one side and missed on the other fails loudly at import.
_INFO_COLUMNS: dict[str, str] = {
    "fullName": "full_name",
    "professionalTitle": "professional_title",
    "email": "email",
    "phone": "phone",
    "street": "street",
    "city": "city",
    "state": "state",
    "postal": "postal",
    "birthday": "birthday",
    "linkedin": "linkedin",
    "website": "website",
    "summary": "summary",
}

assert set(_INFO_COLUMNS) == set(ProfileInfo.model_fields), (
    "ProfileInfo and the profiles table have drifted apart: "
    f"{set(ProfileInfo.model_fields) ^ set(_INFO_COLUMNS)}"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError) as exc:
        # A caller passing a stale non-UUID id should get "not found", not a
        # 500 from deep inside the driver.
        raise ProfileNotFound(str(value)) from exc


def _iso(value: Any) -> str:
    if value is None:
        return ""
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# -- assembling ResumeData -------------------------------------------------


def _load_data(conn: Connection, profile_id: UUID, row) -> ResumeData:
    info = ProfileInfo(**{field: (row._mapping[column] or "")
                          for field, column in _INFO_COLUMNS.items()})

    experience = [
        Experience(
            id=str(r.id),
            company=r.company,
            title=r.title,
            location=r.location,
            startDate=r.start_date,
            endDate=r.end_date,
            current=r.is_current,
            description=r.description,
        )
        for r in conn.execute(
            select(profile_experiences)
            .where(profile_experiences.c.profile_id == profile_id)
            .order_by(profile_experiences.c.sort_order)
        )
    ]

    education = [
        Education(
            id=str(r.id),
            university=r.university,
            degree=r.degree,
            startYear=r.start_year,
            endYear=r.end_year,
            location=r.location,
        )
        for r in conn.execute(
            select(profile_educations)
            .where(profile_educations.c.profile_id == profile_id)
            .order_by(profile_educations.c.sort_order)
        )
    ]

    skills = [
        Skill(id=str(r.id), name=r.name, category=r.category)
        for r in conn.execute(
            select(profile_skills)
            .where(profile_skills.c.profile_id == profile_id)
            .order_by(profile_skills.c.sort_order)
        )
    ]

    return ResumeData(
        profile=info, experience=experience, education=education, skills=skills
    )


def _write_sections(conn: Connection, profile_id: UUID, user_id: UUID, data: ResumeData) -> None:
    """Replace every child row for this profile.

    Delete-then-insert rather than diffing: the sections are small, reordering
    is a first-class edit, and a diff would have to invent identity for rows the
    client renumbers freely.
    """
    for table in (profile_experiences, profile_educations, profile_skills):
        conn.execute(delete(table).where(table.c.profile_id == profile_id))

    if data.experience:
        conn.execute(
            profile_experiences.insert(),
            [
                {
                    "id": uuid7(),
                    "profile_id": profile_id,
                    "user_id": user_id,
                    "company": item.company,
                    "title": item.title,
                    "location": item.location,
                    "start_date": item.startDate,
                    # The CHECK forbids an end date on a current role; trust the
                    # flag and drop the text rather than failing the save.
                    "end_date": "" if item.current else item.endDate,
                    "is_current": item.current,
                    "description": item.description,
                    "sort_order": index,
                }
                for index, item in enumerate(data.experience)
            ],
        )

    if data.education:
        conn.execute(
            profile_educations.insert(),
            [
                {
                    "id": uuid7(),
                    "profile_id": profile_id,
                    "user_id": user_id,
                    "university": item.university,
                    "degree": item.degree,
                    "start_year": item.startYear,
                    "end_year": item.endYear,
                    "location": item.location,
                    "sort_order": index,
                }
                for index, item in enumerate(data.education)
            ],
        )

    if data.skills:
        # (profile_id, name) is unique, so a duplicate in the payload would
        # abort the whole save. Keep the first occurrence.
        seen: set[str] = set()
        rows = []
        for index, item in enumerate(data.skills):
            key = item.name.strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "id": uuid7(),
                    "profile_id": profile_id,
                    "user_id": user_id,
                    "name": item.name.strip(),
                    "category": item.category or "Other",
                    "sort_order": index,
                }
            )
        if rows:
            conn.execute(profile_skills.insert(), rows)


def _row_to_profile(conn: Connection, row) -> Profile:
    return Profile(
        id=str(row.id),
        name=row.name,
        data=_load_data(conn, row.id, row),
        createdAt=_iso(row.created_at),
        updatedAt=_iso(row.updated_at),
    )


# -- profiles ---------------------------------------------------------------


def list_profiles() -> list[Profile]:
    with get_db() as conn:
        rows = conn.execute(
            select(profiles)
            .where(profiles.c.user_id == current_user_id())
            .order_by(profiles.c.created_at)
        ).all()
        return [_row_to_profile(conn, row) for row in rows]


def get_profile(profile_id: str) -> Profile:
    target = _as_uuid(profile_id)
    with get_db() as conn:
        row = conn.execute(select(profiles).where(profiles.c.id == target)).first()
        if row is None:
            raise ProfileNotFound(profile_id)
        return _row_to_profile(conn, row)


def create_profile(payload: ProfileCreate) -> Profile:
    user_id = current_user_id()
    profile_id = uuid7()

    with get_db() as conn:
        # The first profile a user creates becomes their default; the partial
        # unique index allows exactly one.
        has_default = conn.execute(
            select(profiles.c.id).where(
                profiles.c.user_id == user_id, profiles.c.is_default.is_(True)
            )
        ).scalar()

        values: dict[str, Any] = {
            "id": profile_id,
            "user_id": user_id,
            "name": payload.name,
            "is_default": has_default is None,
        }
        values.update(
            {column: getattr(payload.data.profile, field) or ""
             for field, column in _INFO_COLUMNS.items()}
        )
        conn.execute(profiles.insert().values(**values))
        _write_sections(conn, profile_id, user_id, payload.data)

        conn.execute(
            profile_template_settings.insert().values(
                profile_id=profile_id,
                user_id=user_id,
                template_id=_template_uuid(conn, DEFAULT_TEMPLATE_ID),
                template_version=1,
                style_overrides={},
            )
        )
    return get_profile(str(profile_id))


def update_profile(profile_id: str, payload: ProfileUpdate) -> Profile:
    target = _as_uuid(profile_id)
    with get_db() as conn:
        row = conn.execute(select(profiles).where(profiles.c.id == target)).first()
        if row is None:
            raise ProfileNotFound(profile_id)

        values: dict[str, Any] = {"updated_at": func.now()}
        if payload.name is not None:
            values["name"] = payload.name
        if payload.data is not None:
            values.update(
                {column: getattr(payload.data.profile, field) or ""
                 for field, column in _INFO_COLUMNS.items()}
            )

        conn.execute(profiles.update().where(profiles.c.id == target).values(**values))
        if payload.data is not None:
            _write_sections(conn, target, row.user_id, payload.data)

    return get_profile(profile_id)


class LastProfile(RuntimeError):
    """Refusing to delete the only profile."""


def deletion_impact(profile_id: str) -> dict[str, Any]:
    """What deleting this profile would destroy.

    Jobs hang off a profile, and everything derived from a job hangs off that,
    so removing a profile takes its whole pipeline with it. That is the right
    cascade — an extraction belongs to the job it was made for — but it is far
    more than "delete a name", so the caller is told before it happens.
    """
    from app.models import extraction_bullets, extraction_runs, generated_documents, jobs

    target = _as_uuid(profile_id)
    with get_db() as conn:
        row = conn.execute(
            select(profiles.c.name, profiles.c.is_default).where(profiles.c.id == target)
        ).first()
        if row is None:
            raise ProfileNotFound(profile_id)

        def count(query) -> int:
            return conn.execute(query).scalar() or 0

        job_ids = select(jobs.c.id).where(jobs.c.profile_id == target).scalar_subquery()
        run_ids = (
            select(extraction_runs.c.id)
            .where(extraction_runs.c.job_id.in_(job_ids))
            .scalar_subquery()
        )

        impact = {
            "profileId": profile_id,
            "name": row.name,
            "isDefault": row.is_default,
            "jobs": count(select(func.count()).select_from(jobs).where(jobs.c.profile_id == target)),
            "extractions": count(
                select(func.count()).select_from(extraction_runs)
                .where(extraction_runs.c.job_id.in_(job_ids))
            ),
            "bullets": count(
                select(func.count()).select_from(extraction_bullets)
                .where(extraction_bullets.c.role_id.in_(
                    select(extraction_roles.c.id)
                    .where(extraction_roles.c.run_id.in_(run_ids))
                    .scalar_subquery()
                ))
            ),
            "documents": count(
                select(func.count()).select_from(generated_documents)
                .where(generated_documents.c.profile_id == target)
            ),
            "experiences": count(
                select(func.count()).select_from(profile_experiences)
                .where(profile_experiences.c.profile_id == target)
            ),
            "isOnly": count(
                select(func.count()).select_from(profiles)
                .where(profiles.c.user_id == select(profiles.c.user_id)
                       .where(profiles.c.id == target).scalar_subquery())
            ) == 1,
        }
        # Files already written to the output folder stay there; deleting a
        # document someone may have sent is not this button's job.
        impact["filesLeftOnDisk"] = count(
            select(func.count()).select_from(generated_documents).where(
                generated_documents.c.profile_id == target,
                generated_documents.c.storage_key.isnot(None),
            )
        )
    return impact


def delete_profile(profile_id: str) -> dict[str, Any]:
    """Delete a profile and everything that belongs to it.

    Returns what was removed, so the UI can report it rather than just going
    quiet. Refuses the last profile: a job has to belong to one, so deleting it
    would leave the app unable to import anything.
    """
    impact = deletion_impact(profile_id)
    if impact["isOnly"]:
        raise LastProfile(
            f"{impact['name']!r} is your only profile. Create another before "
            "deleting this one — jobs belong to a profile."
        )

    target = _as_uuid(profile_id)
    with get_db() as conn:
        row = conn.execute(
            delete(profiles)
            .where(profiles.c.id == target)
            .returning(profiles.c.user_id, profiles.c.is_default)
        ).first()
        if row is None:
            raise ProfileNotFound(profile_id)

        # Exactly one profile per user is the default, and the partial unique
        # index only stops there being two — it cannot stop there being none.
        if row.is_default:
            successor = conn.execute(
                select(profiles.c.id)
                .where(profiles.c.user_id == row.user_id)
                .order_by(profiles.c.created_at)
                .limit(1)
            ).scalar()
            if successor:
                conn.execute(
                    profiles.update()
                    .where(profiles.c.id == successor)
                    .values(is_default=True)
                )
                impact["promoted"] = str(successor)

    # A setting pointing at a deleted profile would fail later with an error
    # that says nothing about where the stale id came from.
    from app.services import settings_service

    if (settings_service.get_settings().get("resumeProfile") or "") == profile_id:
        settings_service.update_settings({"resumeProfile": ""})
        impact["clearedResumeProfile"] = True

    return impact


# -- template settings ------------------------------------------------------


def _template_uuid(conn: Connection, template_key: str) -> UUID:
    """Map the app's template key ("template-4") to its row id."""
    found = conn.execute(
        select(templates.c.id).where(templates.c.key == template_key)
    ).scalar()
    if found is None:
        raise TemplateNotFound(template_key)
    return found


def _template_key(conn: Connection, template_id: UUID) -> str:
    key = conn.execute(
        select(templates.c.key).where(templates.c.id == template_id)
    ).scalar()
    return key or DEFAULT_TEMPLATE_ID


def _effective_style(template_key: str, overrides: dict) -> dict:
    template = resolve_template(template_key)
    return merge_style(template.defaultStyle, overrides).model_dump()


def get_template_settings(profile_id: str) -> ProfileTemplateSettings:
    target = _as_uuid(profile_id)
    with get_db() as conn:
        if conn.execute(select(profiles.c.id).where(profiles.c.id == target)).scalar() is None:
            raise ProfileNotFound(profile_id)

        row = conn.execute(
            select(profile_template_settings).where(
                profile_template_settings.c.profile_id == target
            )
        ).first()

        if row is None:
            # Profile predates its settings row, or they were reset.
            return ProfileTemplateSettings(
                profileId=profile_id,
                templateId=DEFAULT_TEMPLATE_ID,
                templateVersion=1,
                styleOverrides={},
                effectiveStyle=_effective_style(DEFAULT_TEMPLATE_ID, {}),
                updatedAt=_now(),
            )

        key = _template_key(conn, row.template_id)
        overrides = row.style_overrides or {}
        return ProfileTemplateSettings(
            profileId=profile_id,
            templateId=key,
            templateVersion=row.template_version,
            styleOverrides=overrides,
            effectiveStyle=_effective_style(key, overrides),
            updatedAt=_iso(row.updated_at),
        )


def save_template_settings(
    profile_id: str, template_id: str, style_overrides: dict
) -> ProfileTemplateSettings:
    target = _as_uuid(profile_id)

    template = get_template(template_id)
    if template is None:
        raise TemplateNotFound(template_id)
    if not template.active:
        # Inactive templates stay resolvable for history but cannot be chosen.
        raise TemplateNotFound(f"{template_id} is not active")

    cleaned = validate_overrides(style_overrides)

    with get_db() as conn:
        row = conn.execute(select(profiles.c.user_id).where(profiles.c.id == target)).first()
        if row is None:
            raise ProfileNotFound(profile_id)

        values = {
            "profile_id": target,
            "user_id": row.user_id,
            "template_id": _template_uuid(conn, template.id),
            "template_version": template.version,
            "style_overrides": cleaned,
            "updated_at": func.now(),
        }
        existing = conn.execute(
            select(profile_template_settings.c.profile_id).where(
                profile_template_settings.c.profile_id == target
            )
        ).scalar()
        if existing:
            conn.execute(
                profile_template_settings.update()
                .where(profile_template_settings.c.profile_id == target)
                .values(**values)
            )
        else:
            conn.execute(profile_template_settings.insert().values(**values))

    return get_template_settings(profile_id)


def reset_template_settings(profile_id: str) -> ProfileTemplateSettings:
    """Drop overrides and return to the default template. Content is untouched."""
    return save_template_settings(profile_id, DEFAULT_TEMPLATE_ID, {})
