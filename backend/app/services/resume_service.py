"""Resume PDF orchestration: build payload, render, snapshot, persist."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import get_db
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
        with get_db() as conn:
            conn.execute(
                "INSERT INTO generated_resumes"
                " (id, profile_id, job_application_id, template_id, template_version,"
                "  profile_snapshot_json, style_snapshot_json, layout_snapshot_json,"
                "  file_name, file_path, content_hash, generated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    f"gen-{uuid.uuid4().hex[:12]}",
                    profile_id,
                    job_application_id,
                    payload["templateId"],
                    payload["templateVersion"],
                    json.dumps(payload["data"]),
                    json.dumps(payload["style"]),
                    # User templates are mutable, so pinning id+version alone
                    # would let a later edit rewrite this record's meaning.
                    json.dumps(payload.get("layout") or {}),
                    filename,
                    content_hash(payload),
                    _now(),
                ),
            )

    return pdf_bytes, filename


def list_generated(profile_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM generated_resumes"
    params: tuple = ()
    if profile_id:
        query += " WHERE profile_id = ?"
        params = (profile_id,)
    query += " ORDER BY generated_at DESC"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
