from fastapi import APIRouter, HTTPException

from app.schemas.deepseek import SessionStatusResponse
from app.services.deepseek import session_check

router = APIRouter(prefix="/api/deepseek", tags=["deepseek"])


@router.get("/session", response_model=SessionStatusResponse)
async def get_session(force: bool = False):
    """Whether the stored session actually works right now.

    This loads DeepSeek with the shared profile rather than only inspecting a
    file, so an expired session reports "not connected" instead of showing
    green while every extraction silently falls back.
    """
    return SessionStatusResponse(**await session_check.verify_session(force=force))


@router.post("/sign-out", response_model=SessionStatusResponse)
def sign_out():
    """Forget the stored session. Signs out of the app, not out of DeepSeek."""
    try:
        return SessionStatusResponse(**session_check.sign_out())
    except session_check.SignOutBlocked as exc:
        raise HTTPException(
            status_code=409, detail={"code": "SIGN_OUT_BLOCKED", "message": str(exc)}
        ) from exc
