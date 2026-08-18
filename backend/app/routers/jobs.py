from fastapi import APIRouter, HTTPException

from app.schemas.job import ExtractSkillsRequest, ExtractSkillsResponse, JobListing
from app.services import job_service
from app.services.deepseek import (
    DeepSeekAuthError,
    DeepSeekError,
    DeepSeekService,
    DeepSeekTimeoutError,
)
from app.services.jobright_client import JobrightClient

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobListing])
def list_jobs():
    return job_service.get_jobs()


@router.post("/import", response_model=list[JobListing])
async def import_jobs():
    client = JobrightClient()
    return await client.fetch_jobs()


@router.post("/extract-skills", response_model=ExtractSkillsResponse)
async def extract_skills(payload: ExtractSkillsRequest):
    from app.services.progress import progress

    service = DeepSeekService()
    progress.emit(
        "skills",
        f"Extracting skills from a {len(payload.description)}-character job description…",
        level="step",
        mock=service.mock_mode,
    )
    try:
        skills = await service.extract_skills(payload.description, payload.prompt)
        progress.emit(
            "skills",
            "Skills extracted",
            level="result",
            preview=skills[:200],
        )
    except DeepSeekAuthError as exc:
        progress.emit("skills", f"Failed: {exc}", level="error")
        # 401 so the UI can tell "session expired" apart from a generic failure.
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except DeepSeekTimeoutError as exc:
        progress.emit("skills", f"Timed out: {exc}", level="error")
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except DeepSeekError as exc:
        progress.emit("skills", f"Failed: {exc}", level="error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ExtractSkillsResponse(skills=skills)
