from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict

from app.schemas.deepseek import LoginStatusResponse, SessionStatusResponse
from app.services.deepseek import embedded_login, get_login_status, session_check, start_login

router = APIRouter(prefix="/api/deepseek", tags=["deepseek"])


class InputEvent(BaseModel):
    """A forwarded UI event, in the embedded page's coordinate space."""

    model_config = ConfigDict(extra="forbid")

    type: str
    x: float = 0
    y: float = 0
    dy: float = 0
    text: str = ""
    key: str = ""


@router.post("/embedded-login/start")
def embedded_start():
    """Open the embedded sign-in session and begin streaming frames."""
    return embedded_login.start()


@router.get("/embedded-login/status")
def embedded_status():
    status = embedded_login.status()
    if status["status"] == "success":
        # The profile now holds a real session; drop the stale verdict.
        session_check.invalidate()
    return status


@router.get("/embedded-login/frame")
def embedded_frame():
    """Latest screenshot of the embedded page."""
    image = embedded_login.frame()
    if image is None:
        return Response(status_code=204)
    return Response(
        content=image,
        media_type="image/jpeg",
        # Always refetch; this is a live view.
        headers={"Cache-Control": "no-store"},
    )


@router.post("/embedded-login/input")
def embedded_input(event: InputEvent):
    embedded_login.send(event.model_dump())
    return {"ok": True}


@router.post("/embedded-login/stop")
def embedded_stop(sessionId: int | None = None):
    # sessionId guards against a superseded mount tearing down a newer session.
    embedded_login.stop(sessionId)
    return embedded_login.status()


@router.get("/session", response_model=SessionStatusResponse)
async def get_session(force: bool = False):
    """Whether the stored session actually works right now.

    This loads DeepSeek with the saved session rather than only inspecting the
    file, so an expired session reports "not connected" instead of showing green
    while every extraction silently falls back.
    """
    return SessionStatusResponse(**await session_check.verify_session(force=force))


@router.post("/login", response_model=LoginStatusResponse)
async def login():
    """Open the sign-in window. Returns immediately; poll /login/status."""
    # The old result describes the session being replaced.
    session_check.invalidate()
    return LoginStatusResponse(**await start_login())


@router.get("/login/status", response_model=LoginStatusResponse)
def login_status():
    status = get_login_status()
    # A completed sign-in wrote a new session file; drop the cached verdict so
    # the next status call re-checks instead of serving the pre-login answer.
    if status.get("status") == "success":
        session_check.invalidate()
    return LoginStatusResponse(**status)
