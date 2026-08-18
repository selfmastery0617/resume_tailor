from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.resume import ResumeData
from app.services import resume_service, tailored_resume_service
from app.services.pdf.generator import PdfGenerationError
from app.services.pdf.render_cache import render_cache
from app.services.profile_service import ProfileNotFound
from app.services.tailored_resume_service import TailoredResumeError

router = APIRouter(tags=["resumes"])


class GenerateResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profileId: str
    templateId: str | None = None
    draftData: ResumeData | None = None
    styleOverrides: dict = Field(default_factory=dict)
    # inline=True renders in the browser instead of downloading.
    inline: bool = False


def _failed(message: str, retryable: bool = True) -> HTTPException:
    # RG-FR-025: structured, machine-readable error.
    return HTTPException(
        status_code=502,
        detail={"code": "PDF_GENERATION_FAILED", "message": message, "retryable": retryable},
    )


@router.post("/api/resumes/generate")
async def generate_resume(payload: GenerateResumeRequest):
    try:
        pdf_bytes, filename = await resume_service.generate_resume_pdf(
            profile_id=payload.profileId,
            template_id=payload.templateId,
            draft_data=payload.draftData,
            style_overrides=payload.styleOverrides,
        )
    except ProfileNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROFILE_NOT_FOUND", "message": "The profile does not exist."},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "INVALID_STYLE", "message": str(exc)}
        ) from exc
    except PdfGenerationError as exc:
        raise _failed(str(exc)) from exc

    disposition = "inline" if payload.inline else "attachment"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.get("/api/render/{token}")
def get_render_payload(token: str):
    """Payload for the print route.

    Tokens are single-use and expire after five minutes; an unknown or expired
    token is indistinguishable from a wrong one.
    """
    payload = render_cache.get(token)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "RENDER_TOKEN_INVALID", "message": "Token is invalid or expired."},
        )
    return payload


@router.get("/api/resumes/generated")
def list_generated(profileId: str | None = None):
    return resume_service.list_generated(profileId)


# -- tailored resumes, saved into the output folder ------------------------


class TailoredResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobId: str
    company: str = ""
    jobTitle: str = ""
    # Overrides the Settings choice for a one-off generation.
    profileId: str | None = None


@router.post("/api/resumes/tailored")
async def generate_tailored_resume(payload: TailoredResumeRequest):
    """Render the extracted experience to a PDF and save it under the output folder."""
    # Regenerating would overwrite the file on disk, which for an applied job is
    # the document that was actually sent.
    from app.services import job_store

    if job_store.is_locked(payload.jobId):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "JOB_LOCKED",
                "message": "This job is marked applied, so its resume can no longer be regenerated.",
            },
        )

    try:
        return await tailored_resume_service.generate_for_job(
            job_id=payload.jobId,
            company=payload.company,
            job_title=payload.jobTitle,
            profile_id=payload.profileId,
        )
    except TailoredResumeError as exc:
        # Everything in this class is user-fixable (no folder, no extraction,
        # no profile), so it is a 400 with the fix in the message.
        raise HTTPException(
            status_code=400, detail={"code": "TAILORED_RESUME_FAILED", "message": str(exc)}
        ) from exc
    except ProfileNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROFILE_NOT_FOUND", "message": "The profile does not exist."},
        ) from exc
    except PdfGenerationError as exc:
        raise _failed(str(exc)) from exc


@router.get("/api/resumes/tailored")
def list_tailored_resumes():
    """Every saved resume, so the table can restore badges after a refresh."""
    return tailored_resume_service.all_records()


@router.get("/api/resumes/tailored/{job_id}/file")
def download_tailored_resume(job_id: str):
    """Serve the file from disk, so the badge opens the same PDF that was saved."""
    try:
        pdf_bytes, filename = tailored_resume_service.read_pdf(job_id)
    except TailoredResumeError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "RESUME_NOT_FOUND", "message": str(exc)}
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
