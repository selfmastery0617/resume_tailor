"""Cover letter PDF orchestration: build payload, render, snapshot, persist.

Mirrors resume_service.py's build_render_payload/generate_resume_pdf, reusing
the same generate_pdf() (pdf/generator.py -- already generic, dispatches on
payload.documentType for page geometry, see _page_spec's docstring) and
record_document() (kind="cover_letter") rather than duplicating either.
"""

from typing import Any

from app.schemas.cover_letter import CoverLetterData
from app.schemas.cover_letter_style import merge_cover_letter_style, validate_cover_letter_overrides
from app.services import profile_service
from app.services.cover_letter_service import get_cover_letter_template_settings
from app.services.cover_letter_templates.registry import resolve_cover_letter_template
from app.services.pdf.filename import build_cover_letter_pdf_filename
from app.services.pdf.generator import generate_pdf
from app.services.resume_service import record_document


def build_cover_letter_render_payload(
    profile_id: str,
    cover_letter_data: CoverLetterData,
    template_id: str | None = None,
    style_overrides: dict | None = None,
) -> tuple[dict[str, Any], str]:
    """Assemble everything the print route needs. Returns (payload, filename).

    `cover_letter_data` is the step 10 XML, already parsed -- generated once
    per extraction, never re-derived here. One-time style overrides are used
    for rendering only, same as build_render_payload's (never written back
    to the profile).
    """
    profile = profile_service.get_profile(profile_id)
    saved = get_cover_letter_template_settings(profile_id)

    template = resolve_cover_letter_template(template_id or saved.templateId)

    one_time = validate_cover_letter_overrides(style_overrides)
    style = merge_cover_letter_style(template.defaultStyle, saved.styleOverrides, one_time)

    payload: dict[str, Any] = {
        "documentType": "coverLetter",
        "templateId": template.id,
        "data": cover_letter_data.model_dump(),
        "style": style.model_dump(),
    }
    return payload, build_cover_letter_pdf_filename(profile.name, template.id)


async def generate_cover_letter_pdf(
    profile_id: str,
    cover_letter_data: CoverLetterData,
    template_id: str | None = None,
    style_overrides: dict | None = None,
    job_application_id: str | None = None,
    persist: bool = True,
) -> tuple[bytes, str]:
    """Generate a cover letter PDF and record an immutable snapshot.

    Returns (bytes, filename). Mirrors generate_resume_pdf exactly.
    """
    payload, filename = build_cover_letter_render_payload(
        profile_id, cover_letter_data, template_id, style_overrides
    )
    pdf_bytes, page_count = await generate_pdf(payload)

    if persist:
        record_document(
            profile_id=profile_id,
            job_id=job_application_id,
            payload=payload,
            file_name=filename,
            byte_size=len(pdf_bytes),
            page_count=page_count,
            kind="cover_letter",
        )

    return pdf_bytes, filename
