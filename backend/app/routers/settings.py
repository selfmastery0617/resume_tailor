from ipaddress import ip_address

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.services import settings_service

router = APIRouter(prefix="/api", tags=["settings"])


class SettingsPatch(BaseModel):
    # extra="allow" so unknown keys reach validate_settings() and produce a
    # descriptive 400 rather than being silently dropped.
    model_config = ConfigDict(extra="allow")


class FolderCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class FolderSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initialPath: str | None = None


@router.get("/settings")
def get_settings():
    return settings_service.get_settings()


@router.put("/settings")
def update_settings(patch: SettingsPatch):
    try:
        return settings_service.update_settings(patch.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "INVALID_SETTING", "message": str(exc)}
        ) from exc


@router.post("/settings/check-folder")
def check_folder(payload: FolderCheckRequest):
    return settings_service.check_folder(payload.path)


@router.post("/settings/select-folder")
def select_folder(payload: FolderSelectRequest, request: Request):
    """Open a native dialog only for a frontend running on this machine."""
    client_host = request.client.host if request.client else ""
    try:
        is_local = ip_address(client_host).is_loopback
    except ValueError:
        is_local = False
    if not is_local:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "LOCAL_ONLY",
                "message": "The native folder picker is only available through the local backend.",
            },
        )

    try:
        return settings_service.select_folder(payload.initialPath)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "FOLDER_PICKER_UNAVAILABLE",
                "message": f"Could not open the folder picker: {exc}",
            },
        ) from exc


# ChatGPT sign-in lives in routers/chatgpt.py, beside the other providers.
