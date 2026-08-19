from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.schemas.job import ExtractSkillsRequest, ExtractSkillsResponse, StoredJob
from app.services import job_store
from app.services.job_store import JobNotFound
from app.services.deepseek import (
    DeepSeekAuthError,
    DeepSeekError,
    DeepSeekService,
    DeepSeekTimeoutError,
)
from app.services.jobright_client import JobrightClient

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _not_found(job_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "JOB_NOT_FOUND", "message": f"No stored job with id {job_id}."},
    )


@router.get("", response_model=list[StoredJob])
def list_jobs():
    """Every stored job, so the table survives a reload without re-importing."""
    return job_store.list_jobs()


@router.post("/import", response_model=list[StoredJob])
async def import_jobs():
    """Fetch from the source and store. Returns everything held, not just the new.

    Rows already marked applied keep their details — re-importing must not
    rewrite the listing a submitted application was based on.
    """
    client = JobrightClient()
    listings = await client.fetch_jobs()
    return job_store.upsert_many(listings)


class JobPatch(BaseModel):
    """One table edit. Only the fields present are changed."""

    model_config = ConfigDict(extra="forbid")

    date_added: str | None = None
    title: str | None = None
    company: str | None = None
    url: str | None = None
    location: str | None = None
    status: str | None = None


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_added: str | None = None
    title: str = ""
    company: str = ""
    url: str = ""
    location: str = ""


class DeleteRowsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobIds: list[str]


def _bad_edit(exc: Exception, code: str = "INVALID_EDIT") -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": str(exc)})


@router.post("", response_model=StoredJob, status_code=201)
def create_job(payload: CreateJobRequest):
    """A row typed or pasted into the empty row at the bottom of the table."""
    try:
        return job_store.create_job(payload.model_dump(exclude_none=True))
    except job_store.NoProfile as exc:
        raise _bad_edit(exc, "NO_PROFILE") from exc
    except ValueError as exc:
        raise _bad_edit(exc) from exc


@router.patch("/{job_id}", response_model=StoredJob)
def update_job(job_id: str, payload: JobPatch):
    """Apply one cell edit. Absent fields are left alone."""
    patch = payload.model_dump(exclude_unset=True)
    try:
        return job_store.update_job(job_id, patch)
    except JobNotFound as exc:
        raise _not_found(job_id) from exc
    except job_store.JobLocked as exc:
        raise _bad_edit(exc, "STATUS_LOCKED") from exc
    except ValueError as exc:
        raise _bad_edit(exc) from exc


@router.post("/delete-rows")
def delete_rows(payload: DeleteRowsRequest):
    """Remove whole rows — Ctrl+Delete, not clearing their cells."""
    return job_store.delete_many(payload.jobIds)


@router.post("/{job_id}/apply", response_model=StoredJob)
def mark_applied(job_id: str):
    """Record that this job was applied to. The row is read-only afterwards."""
    try:
        return job_store.mark_applied(job_id)
    except JobNotFound as exc:
        raise _not_found(job_id) from exc


@router.delete("/{job_id}")
def delete_job(job_id: str):
    """Delete a job and everything derived from it.

    Any PDF already written to the output folder is left on disk; its path comes
    back in the response so the UI can say where it is.
    """
    try:
        return job_store.delete_job(job_id)
    except JobNotFound as exc:
        raise _not_found(job_id) from exc


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
