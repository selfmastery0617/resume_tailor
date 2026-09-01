from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app.schemas.cover_letter_style import CoverLetterStyle
from app.schemas.cover_letter_template import CoverLetterTemplateListResponse
from app.services import tailored_cover_letter_service
from app.services.cover_letter_templates.registry import list_cover_letter_templates
from app.services.pdf.generator import PdfGenerationError
from app.services.profile_service import ProfileNotFound
from app.services.tailored_resume_service import TailoredResumeError

router = APIRouter(tags=["cover-letters"])


def _failed(message: str, retryable: bool = True) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={"code": "PDF_GENERATION_FAILED", "message": message, "retryable": retryable},
    )


@router.get("/api/cover-letter-templates", response_model=CoverLetterTemplateListResponse)
def get_cover_letter_templates():
    """The 10 built-in presets -- there are no user-created cover letter
    templates (see cover_letter_templates/registry.py's docstring)."""
    return CoverLetterTemplateListResponse(
        templates=list_cover_letter_templates(),
        systemDefaultStyle=CoverLetterStyle().model_dump(),
    )


# -- tailored cover letters, saved into the output folder -------------------


class TailoredCoverLetterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobId: str
    company: str = ""
    jobTitle: str = ""
    profileId: str | None = None


@router.post("/api/cover-letters/tailored")
async def generate_tailored_cover_letter(payload: TailoredCoverLetterRequest):
    """Render the extraction's cover letter to a PDF and save it under the
    output folder, alongside the resume."""
    from app.services import job_store

    if job_store.is_locked(payload.jobId):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "JOB_LOCKED",
                "message": "This job is marked applied, so its cover letter can no longer be regenerated.",
            },
        )

    try:
        record = await tailored_cover_letter_service.generate_for_job(
            job_id=payload.jobId,
            company=payload.company,
            job_title=payload.jobTitle,
            profile_id=payload.profileId,
        )
    except TailoredResumeError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "TAILORED_COVER_LETTER_FAILED", "message": str(exc)}
        ) from exc
    except ProfileNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROFILE_NOT_FOUND", "message": "The profile does not exist."},
        ) from exc
    except PdfGenerationError as exc:
        raise _failed(str(exc)) from exc

    if record is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "NO_COVER_LETTER",
                "message": "This job's extraction has no cover letter yet.",
            },
        )
    return record


@router.get("/api/cover-letters/tailored")
def list_tailored_cover_letters():
    """Every saved cover letter, so the table can restore badges after a refresh."""
    return tailored_cover_letter_service.all_cover_letter_records()


@router.get("/api/cover-letters/tailored/{job_id}/file")
def download_tailored_cover_letter(job_id: str):
    try:
        pdf_bytes, filename = tailored_cover_letter_service.read_cover_letter_pdf(job_id)
    except TailoredResumeError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "COVER_LETTER_NOT_FOUND", "message": str(exc)}
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/api/cover-letters/tailored/{job_id}/open-folder")
def open_tailored_cover_letter_folder(job_id: str):
    try:
        tailored_cover_letter_service.open_cover_letter_folder(job_id)
    except TailoredResumeError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "COVER_LETTER_NOT_FOUND", "message": str(exc)}
        ) from exc
    return {"ok": True}
