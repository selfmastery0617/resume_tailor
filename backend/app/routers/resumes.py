from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.resume import ResumeData
from app.services import resume_service
from app.services.pdf.generator import PdfGenerationError
from app.services.pdf.render_cache import render_cache
from app.services.profile_service import ProfileNotFound

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
