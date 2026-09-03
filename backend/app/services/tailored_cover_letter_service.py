"""Tailored cover letter PDFs.

Turns step 10's parsed <cover_letter> XML (stored on the extraction run --
see experience_service.py's _store_run/_load_run) into a cover letter PDF and
writes it to the *same* per-job folder the resume uses:

    <outputFolder>/<Profile Name>/<mm-dd-yy-HHMM>_<Company>_<Job Title>/<Profile Name>_cover_letter.pdf

Mirrors tailored_resume_service.py's generate_for_job() closely, reusing its
resolve_profile()/_output_root() rather than duplicating them.
"""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import get_db
from app.models import generated_documents, profiles
from app.schemas.cover_letter import CoverLetterData
from app.services import cover_letter_render_service, experience_service, profile_service
from app.services.pdf.filename import (
    build_job_folder_name,
    build_profile_folder_name,
    build_tailored_cover_letter_filename,
)
from app.services.progress import progress
from app.services.tailored_resume_service import (
    TailoredResumeError,
    _extraction_folder_timestamp,
    _output_root,
    _page_count_of,
    resolve_profile,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _cover_letter_data(profile: profile_service.Profile, cover_letter: dict[str, Any]) -> CoverLetterData:
    info = profile.data.profile
    return CoverLetterData(
        jobTitle=cover_letter.get("job_title") or "",
        companyName=cover_letter.get("company_name") or "",
        candidateName=info.fullName or cover_letter.get("signature_name") or "",
        phone=info.phone,
        email=info.email,
        linkedin=info.linkedin,
        greeting=cover_letter.get("greeting") or "Dear Hiring Manager,",
        paragraphs=[p for p in (cover_letter.get("paragraphs") or []) if p],
        closing=cover_letter.get("closing") or "Sincerely,",
    )


async def generate_for_job(
    job_id: str,
    company: str,
    job_title: str,
    profile_id: str | None = None,
) -> dict[str, Any] | None:
    """Render the tailored cover letter PDF, save it alongside the resume,
    and record it. Returns None (rather than raising) when the extraction
    has no cover letter yet -- step 10 is best-effort, same as every other
    step, so a missing cover letter should not block resume generation.
    """
    experience = experience_service.get_experience(job_id)
    if experience is None:
        raise TailoredResumeError(
            "Extract experience for this job before generating a cover letter."
        )

    cover_letter = experience.get("coverLetter") or {}
    if not cover_letter.get("paragraphs"):
        progress.emit(
            "coverletter",
            "No cover letter available for this job — skipping cover letter PDF",
            level="warn",
        )
        return None

    root = _output_root()
    profile = resolve_profile(profile_id)

    folder = root / build_profile_folder_name(profile.name) / build_job_folder_name(
        company, job_title, when=_extraction_folder_timestamp(experience)
    )
    file_name = build_tailored_cover_letter_filename(profile.name)
    destination = folder / file_name

    progress.emit(
        "coverletter",
        f"Building cover letter for “{job_title or 'this role'}” as {profile.name}",
        level="step",
        folder=str(folder),
    )

    data = _cover_letter_data(profile, cover_letter)
    render_payload, _ = cover_letter_render_service.build_cover_letter_render_payload(
        profile.id, data
    )
    pdf_bytes, _download_name = await cover_letter_render_service.generate_cover_letter_pdf(
        profile_id=profile.id,
        cover_letter_data=data,
        job_application_id=job_id,
        persist=False,
    )

    try:
        folder.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(pdf_bytes)
    except OSError as exc:
        raise TailoredResumeError(
            f"Could not write {destination}: {exc.strerror or exc}"
        ) from exc

    from app.services.resume_service import record_document

    record_document(
        profile_id=profile.id,
        job_id=job_id,
        payload=render_payload,
        file_name=file_name,
        byte_size=len(pdf_bytes),
        page_count=_page_count_of(pdf_bytes),
        storage_key=str(destination),
        kind="cover_letter",
    )

    record = {
        "jobId": job_id,
        "profileId": profile.id,
        "profileName": profile.name,
        "templateId": render_payload["templateId"],
        "folder": str(folder),
        "fileName": file_name,
        "filePath": str(destination),
        "pageCount": _page_count_of(pdf_bytes),
        "byteSize": len(pdf_bytes),
        "generatedAt": _now(),
    }

    progress.emit(
        "coverletter",
        f"Saved {file_name} ({record['pageCount']} page"
        f"{'s' if record['pageCount'] != 1 else ''}) to {folder}",
        level="result",
        preview=str(destination),
    )
    # Read back rather than returning `record`: the listing endpoint adds an
    # `exists` flag, and a response that omitted it would leave the freshly
    # generated row rendering as "file missing".
    return get_cover_letter_record(job_id) or record


# -- persistence -------------------------------------------------------------


def _row_to_record(row) -> dict[str, Any]:
    record = {
        "jobId": str(row.job_id) if row.job_id else "",
        "profileId": str(row.profile_id),
        "profileName": row.profile_name or "",
        # No DB row to resolve back to a preset id (cover letter templates
        # have none -- see cover_letter_templates/registry.py's docstring),
        # so this stays blank for a record read back after the fact.
        "templateId": "",
        "folder": str(Path(row.storage_key).parent) if row.storage_key else "",
        "fileName": row.file_name,
        "filePath": row.storage_key or "",
        "pageCount": row.page_count,
        "byteSize": row.byte_size,
        "generatedAt": row.generated_at.isoformat() if row.generated_at else "",
    }
    record["exists"] = bool(row.storage_key) and Path(row.storage_key).is_file()
    return record


def _saved_documents():
    """Cover letter documents written to the output folder, newest per job."""
    from sqlalchemy import select

    return (
        select(
            generated_documents.c.job_id,
            generated_documents.c.profile_id,
            generated_documents.c.file_name,
            generated_documents.c.storage_key,
            generated_documents.c.page_count,
            generated_documents.c.byte_size,
            generated_documents.c.generated_at,
            profiles.c.name.label("profile_name"),
        )
        .select_from(
            generated_documents.join(profiles, profiles.c.id == generated_documents.c.profile_id)
        )
        .where(
            generated_documents.c.storage_key.isnot(None),
            generated_documents.c.deleted_at.is_(None),
            generated_documents.c.kind == "cover_letter",
        )
    )


def get_cover_letter_record(job_id: str) -> dict[str, Any] | None:
    from app.services import job_store

    with get_db() as conn:
        job_row = job_store._find(conn, job_id)
        if job_row is None:
            return None
        row = conn.execute(
            _saved_documents()
            .where(generated_documents.c.job_id == job_row.id)
            .order_by(generated_documents.c.generated_at.desc())
            .limit(1)
        ).first()
    return _row_to_record(row) if row else None


def all_cover_letter_records() -> dict[str, dict[str, Any]]:
    """Every saved cover letter, so the table can restore its badges after a reload."""
    with get_db() as conn:
        rows = conn.execute(
            _saved_documents().order_by(generated_documents.c.generated_at.desc())
        ).all()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.job_id) if row.job_id else ""
        if key and key not in out:
            out[key] = _row_to_record(row)
    return out


def read_cover_letter_pdf(job_id: str) -> tuple[bytes, str]:
    """Bytes of the saved cover letter PDF, for serving it back to the browser."""
    record = get_cover_letter_record(job_id)
    if record is None:
        raise TailoredResumeError("No cover letter has been generated for this job.")
    path = Path(record["filePath"])
    if not path.is_file():
        raise TailoredResumeError(f"The saved file is missing: {path}")
    return path.read_bytes(), record["fileName"]


def open_cover_letter_folder(job_id: str) -> None:
    """Open the saved cover letter's folder in Explorer, file selected."""
    record = get_cover_letter_record(job_id)
    if record is None:
        raise TailoredResumeError("No cover letter has been generated for this job.")

    path = Path(record["filePath"])
    if path.is_file():
        subprocess.Popen(["explorer", "/select,", str(path)])
        return

    folder = Path(record["folder"])
    if folder.is_dir():
        subprocess.Popen(["explorer", str(folder)])
        return

    raise TailoredResumeError(f"The saved file and its folder are both missing: {path}")
