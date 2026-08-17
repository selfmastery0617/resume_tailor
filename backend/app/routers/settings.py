from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.services import settings_service
from app.services.chatgpt import chatgpt_login

router = APIRouter(prefix="/api", tags=["settings"])


class SettingsPatch(BaseModel):
    # extra="allow" so unknown keys reach validate_settings() and produce a
    # descriptive 400 rather than being silently dropped.
    model_config = ConfigDict(extra="allow")


class FolderCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


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


# -- ChatGPT sign-in ------------------------------------------------------


@router.get("/chatgpt/session")
def chatgpt_session():
    return chatgpt_login.session_status()


@router.post("/chatgpt/login")
async def chatgpt_start_login():
    return await chatgpt_login.start_login()


@router.get("/chatgpt/login/status")
def chatgpt_login_status():
    return chatgpt_login.login_status()


@router.post("/chatgpt/sign-out")
def chatgpt_sign_out():
    chatgpt_login.sign_out()
    return chatgpt_login.session_status()
