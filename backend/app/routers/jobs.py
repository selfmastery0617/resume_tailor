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


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Free text from the dialog: "Senior Data Engineer, Data Engineer".
    roles: list[str] = []
    limit: int = 10
    excludeCompanies: list[str] = []


@router.post("/import")
async def start_import(payload: ImportRequest):
    """Begin an import and return immediately.

    The feed is paginated and a run takes a while, so this starts a background
    task; the dialog polls /import/status for progress and the table refreshes
    as rows are stored.

    Async on purpose: a sync path operation runs in a worker thread, where
    asyncio.create_task has no loop to attach the run to.
    """
    from app.services.job_import import ImportBusy, importer

    try:
        return importer.start(payload.roles, payload.limit, payload.excludeCompanies)
    except ImportBusy as exc:
        raise HTTPException(
            status_code=409, detail={"code": "IMPORT_RUNNING", "message": str(exc)}
        ) from exc


@router.get("/import/status")
def import_status():
    """Progress for the dialog: how many scanned, how many matched, and state."""
    from app.services.job_import import importer

    return importer.snapshot()


@router.post("/import/cancel")
def cancel_import():
    """Stop the run. It stops between pages, so rows already found are kept."""
    from app.services.job_import import importer

    return importer.cancel()


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
