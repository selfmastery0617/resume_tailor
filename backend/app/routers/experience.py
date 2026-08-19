from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.experience_db import ExperienceDatabaseError
from app.services import experience_db_store, experience_service, settings_service, vector_search
from app.services.experience_service import ExperienceExtractionError

router = APIRouter(prefix="/api/experience", tags=["experience"])


class SaveDatabaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Raw editor text, so JSON syntax errors can be reported with line/column.
    text: str


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobId: str
    jobDescription: str
    jobTitle: str = ""
    jobMission: str = ""
    techSkills: list[str] = Field(default_factory=list)


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _resolve_profile(profile_id: str | None) -> str:
    """Which profile's corpus to act on. Defaults to the active one."""
    from app.services import job_store

    if profile_id:
        return profile_id
    try:
        return str(job_store.active_profile_id())
    except job_store.NoProfile as exc:
        raise _bad_request("NO_PROFILE", str(exc)) from exc


@router.get("/database")
def get_database(profileId: str | None = None):
    """One profile's corpus: raw text for the editor, plus its company list."""
    target = _resolve_profile(profileId)
    text = experience_db_store.load_raw(target)

    if not text:
        # No corpus yet is a normal state for a new profile, not an error.
        return {
            "text": "",
            "companies": [],
            "path": str(experience_db_store.path(target)),
            "profileId": target,
            "exists": False,
            "valid": True,
            "detail": None,
        }

    try:
        db = experience_db_store.load_database(target)
    except ExperienceDatabaseError as exc:
        # Still return the text so the user can fix it in the editor.
        return {
            "text": text,
            "companies": [],
            "path": str(experience_db_store.path(target)),
            "profileId": target,
            "exists": True,
            "valid": False,
            "detail": str(exc),
        }

    return {
        "text": text,
        "companies": db.company_names(),
        "path": str(experience_db_store.path(target)),
        "profileId": target,
        "exists": True,
        "valid": True,
        "detail": None,
    }


@router.put("/database")
def save_database(payload: SaveDatabaseRequest, profileId: str | None = None):
    target = _resolve_profile(profileId)
    try:
        db = experience_db_store.save_raw_text(target, payload.text)
    except ExperienceDatabaseError as exc:
        raise _bad_request("INVALID_DATABASE", str(exc)) from exc
    # Company list is returned so the dropdown updates without a second call.
    return {
        "companies": db.company_names(),
        "profileId": target,
        "exists": True,
        "valid": True,
        "detail": None,
    }


@router.get("/database/example")
def database_example():
    """The expected shape, for a profile starting from nothing."""
    import json

    return {"text": json.dumps(experience_db_store.SEED, indent=2, ensure_ascii=False)}


@router.get("/progress")
def get_progress(since: int = 0):
    """Events newer than `since`, for the live console."""
    from app.services.progress import progress

    return {"events": progress.since(since), "latest": progress.latest_seq()}


@router.post("/progress/clear")
def clear_progress():
    from app.services.progress import progress

    progress.clear()
    return {"ok": True, "latest": progress.latest_seq()}


@router.get("/search-backend")
def search_backend():
    """Whether ranking is semantic or the lexical fallback."""
    return vector_search.backend()


@router.get("/all")
def all_extractions():
    """Every stored extraction, so the table can restore badges after reload."""
    return experience_service.all_experience()


@router.get("/{job_id}")
def get_extraction(job_id: str):
    found = experience_service.get_experience(job_id)
    if found is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_EXTRACTED", "message": "No experience extracted for this job."},
        )
    return found


@router.post("/extract")
async def extract(payload: ExtractRequest):
    # An applied job is a record of what was sent. Re-extracting would rewrite
    # the bullets behind a submitted application, so the lock is enforced here
    # rather than relying on the button being disabled.
    from app.services import job_store

    if job_store.is_locked(payload.jobId):
        raise _bad_request(
            "JOB_LOCKED",
            "This job is marked applied, so its experience can no longer be changed.",
        )

    first_company = (settings_service.get_settings().get("firstCompany") or "").strip()
    if not first_company:
        raise _bad_request(
            "NO_FIRST_COMPANY", "Please select a First Company in Settings first."
        )

    target = _resolve_profile(None)
    try:
        db = experience_db_store.load_database(target)
    except experience_db_store.CorpusNotFound as exc:
        raise _bad_request(
            "NO_CORPUS",
            "This profile has no database.json yet. Add one on the Profile tab "
            "before extracting.",
        ) from exc
    except ExperienceDatabaseError as exc:
        raise _bad_request("INVALID_DATABASE", str(exc)) from exc

    # The title step is asked to improve on what the profile already claims, so
    # it needs to know what that is.
    from app.services import profile_service

    try:
        current_title = profile_service.get_profile(target).data.profile.professionalTitle
    except profile_service.ProfileNotFound:
        current_title = ""

    try:
        result = await experience_service.extract_experience(
            db=db,
            first_company=first_company,
            job_description=payload.jobDescription,
            tech_skills=payload.techSkills,
            job_title=payload.jobTitle,
            job_mission=payload.jobMission,
            current_title=current_title,
        )
    except ExperienceExtractionError as exc:
        raise _bad_request("EXTRACTION_FAILED", str(exc)) from exc

    experience_service.save_experience(payload.jobId, result)
    return result
