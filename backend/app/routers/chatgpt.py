from fastapi import APIRouter, HTTPException

from app.schemas.deepseek import SessionStatusResponse
from app.services import chatgpt_session

router = APIRouter(prefix="/api/chatgpt", tags=["chatgpt"])


@router.get("/session", response_model=SessionStatusResponse)
async def get_session(force: bool = False):
    """Whether the stored session actually works right now.

    Loads ChatGPT with the shared profile rather than only inspecting a file,
    so an expired session reports "not connected" instead of showing green.
    """
    return SessionStatusResponse(**await chatgpt_session.verify_session(force=force))


@router.post("/sign-out", response_model=SessionStatusResponse)
def sign_out():
    """Forget the stored session. Signs out of the app, not out of ChatGPT."""
    try:
        return SessionStatusResponse(**chatgpt_session.sign_out())
    except chatgpt_session.SignOutBlocked as exc:
        raise HTTPException(
            status_code=409, detail={"code": "SIGN_OUT_BLOCKED", "message": str(exc)}
        ) from exc
