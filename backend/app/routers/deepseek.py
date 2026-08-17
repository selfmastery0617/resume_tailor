from fastapi import APIRouter

from app.schemas.deepseek import LoginStatusResponse, SessionStatusResponse
from app.services.deepseek import get_login_status, session_status, start_login

router = APIRouter(prefix="/api/deepseek", tags=["deepseek"])


@router.get("/session", response_model=SessionStatusResponse)
def get_session():
    """Whether a usable DeepSeek session exists right now."""
    return SessionStatusResponse(**session_status())


@router.post("/login", response_model=LoginStatusResponse)
async def login():
    """Open the sign-in window. Returns immediately; poll /login/status."""
    return LoginStatusResponse(**await start_login())


@router.get("/login/status", response_model=LoginStatusResponse)
def login_status():
    return LoginStatusResponse(**get_login_status())
