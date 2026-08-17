from fastapi import APIRouter, HTTPException

from app.schemas.resume import Profile, ProfileCreate, ProfileUpdate
from app.schemas.template import ProfileTemplateSettings, SaveTemplateSettingsRequest
from app.services import profile_service
from app.services.profile_service import ProfileNotFound, TemplateNotFound

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"code": "PROFILE_NOT_FOUND", "message": message}
    )


@router.get("", response_model=list[Profile])
def list_profiles():
    return profile_service.list_profiles()


@router.post("", response_model=Profile, status_code=201)
def create_profile(payload: ProfileCreate):
    return profile_service.create_profile(payload)


@router.get("/{profile_id}", response_model=Profile)
def get_profile(profile_id: str):
    try:
        return profile_service.get_profile(profile_id)
    except ProfileNotFound as exc:
        raise _not_found("The requested profile does not exist.") from exc


@router.put("/{profile_id}", response_model=Profile)
def update_profile(profile_id: str, payload: ProfileUpdate):
    try:
        return profile_service.update_profile(profile_id, payload)
    except ProfileNotFound as exc:
        raise _not_found("The requested profile does not exist.") from exc


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: str):
    try:
        profile_service.delete_profile(profile_id)
    except ProfileNotFound as exc:
        raise _not_found("The requested profile does not exist.") from exc


# -- template settings ----------------------------------------------------


@router.get("/{profile_id}/template", response_model=ProfileTemplateSettings)
def get_template_settings(profile_id: str):
    try:
        return profile_service.get_template_settings(profile_id)
    except ProfileNotFound as exc:
        raise _not_found("The requested profile does not exist.") from exc


@router.put("/{profile_id}/template", response_model=ProfileTemplateSettings)
def save_template_settings(profile_id: str, payload: SaveTemplateSettingsRequest):
    try:
        return profile_service.save_template_settings(
            profile_id, payload.templateId, payload.styleOverrides
        )
    except ProfileNotFound as exc:
        raise _not_found("The requested profile does not exist.") from exc
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "TEMPLATE_NOT_FOUND", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        # Invalid style values / unknown fields -> 400, never a 500.
        raise HTTPException(
            status_code=400, detail={"code": "INVALID_STYLE", "message": str(exc)}
        ) from exc


@router.delete("/{profile_id}/template", response_model=ProfileTemplateSettings)
def reset_template_settings(profile_id: str):
    try:
        return profile_service.reset_template_settings(profile_id)
    except ProfileNotFound as exc:
        raise _not_found("The requested profile does not exist.") from exc
