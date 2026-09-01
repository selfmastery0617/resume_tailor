"""Resume PDF orchestration: build payload, render, snapshot, persist."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db import get_db
from app.ids import uuid7
from app.models import generated_documents, profiles, templates
from app.schemas.resume import ResumeData
from app.schemas.style import merge_style, validate_overrides
from app.services import profile_service
from app.services.pdf.filename import build_pdf_filename
from app.services.pdf.generator import content_hash, generate_pdf
from app.services.templates.registry import resolve_template


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_render_payload(
    profile_id: str,
    template_id: str | None = None,
    draft_data: ResumeData | None = None,
    style_overrides: dict | None = None,
) -> tuple[dict[str, Any], str]:
    """Assemble everything the print route needs. Returns (payload, filename).

    Draft data and one-time style overrides are used for rendering only — they
    are never written back to the profile (RG-FR-013, 7.6).
    """
    profile = profile_service.get_profile(profile_id)
    saved = profile_service.get_template_settings(profile_id)

    # Requested template wins; otherwise the profile's saved selection.
    template = resolve_template(template_id or saved.templateId)

    # Precedence: system -> template -> profile overrides -> generation overrides.
    one_time = validate_overrides(style_overrides)
    style = merge_style(template.defaultStyle, saved.styleOverrides, one_time)

    data = draft_data if draft_data is not None else profile.data

    payload: dict[str, Any] = {
        "templateId": template.id,
        "templateVersion": template.version,
        "rendererKey": template.rendererKey,
        "data": data.model_dump(),
        "style": style.model_dump(),
        # Required by the layout-v1 renderer. Without it the print route falls
        # back to the default structure, so a user template would preview one
        # way and print another.
        "layout": template.layout,
    }
    return payload, build_pdf_filename(profile.name, template.id)


async def generate_resume_pdf(
    profile_id: str,
    template_id: str | None = None,
    draft_data: ResumeData | None = None,
    style_overrides: dict | None = None,
    job_application_id: str | None = None,
    persist: bool = True,
) -> tuple[bytes, str]:
    """Generate a PDF and record an immutable snapshot. Returns (bytes, filename)."""
    payload, filename = build_render_payload(
        profile_id, template_id, draft_data, style_overrides
    )
    pdf_bytes, page_count = await generate_pdf(payload)

    if persist:
        # US-RG-02: the snapshot is what makes a historical PDF reproducible;
        # later profile or template-default edits must not alter it.
        record_document(
            profile_id=profile_id,
            job_id=job_application_id,
            payload=payload,
            file_name=filename,
            byte_size=len(pdf_bytes),
        )

    return pdf_bytes, filename


def record_document(
    *,
    profile_id: str,
    job_id: str | None,
    payload: dict[str, Any],
    file_name: str,
    byte_size: int = 0,
    page_count: int = 0,
    storage_key: str | None = None,
    kind: str = "resume",
) -> UUID:
    """Write the immutable record of one generated document.

    generated_resumes and job_resume used to be separate tables saying
    overlapping things about the same PDF; they are one table now, told apart
    by `kind` and by whether a storage key was written. `kind="cover_letter"`
    is the other supported value (see the DOCUMENT_KINDS / kind_known check
    constraint on generated_documents) -- a cover letter template has no row
    in `templates` (see cover_letter_templates/registry.py's docstring), so
    template_uuid naturally resolves to None for one, same as it already does
    for any templateId this lookup doesn't recognize.
    """
    from app.services import job_store

    with get_db() as conn:
        owner = conn.execute(
            select(profiles.c.user_id).where(profiles.c.id == UUID(str(profile_id)))
        ).scalar()

        template_uuid = conn.execute(
            select(templates.c.id).where(templates.c.key == payload["templateId"])
        ).scalar()

        job_row = job_store._find(conn, job_id) if job_id else None

        document_id = uuid7()
        conn.execute(
            generated_documents.insert().values(
                id=document_id,
                profile_id=UUID(str(profile_id)),
                user_id=owner,
                # Null when nothing prompted it — a profile may hold a generic
                # resume that no listing asked for.
                job_id=job_row.id if job_row is not None else None,
                run_id=None,
                kind=kind,
                template_id=template_uuid,
                template_version=payload.get("templateVersion") or 1,
                content_snapshot=payload["data"],
                style_snapshot=payload["style"],
                # User templates are mutable, so pinning id+version alone would
                # let a later edit rewrite this record's meaning.
                layout_snapshot=payload.get("layout") or {},
                file_name=file_name,
                storage_key=storage_key,
                byte_size=byte_size,
                page_count=page_count,
                content_hash=content_hash(payload),
            )
        )
    return document_id


def list_generated(profile_id: str | None = None) -> list[dict[str, Any]]:
    query = select(generated_documents).where(generated_documents.c.deleted_at.is_(None))
    if profile_id:
        query = query.where(generated_documents.c.profile_id == UUID(str(profile_id)))
    with get_db() as conn:
        rows = conn.execute(
            query.order_by(generated_documents.c.generated_at.desc())
        ).all()
    return [
        {
            key: (str(value) if isinstance(value, UUID) else value)
            for key, value in row._mapping.items()
        }
        for row in rows
    ]
