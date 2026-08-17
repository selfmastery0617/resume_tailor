from pydantic import BaseModel


class SessionStatusResponse(BaseModel):
    """Whether a usable DeepSeek session exists right now."""

    connected: bool
    detail: str


class LoginStatusResponse(BaseModel):
    """Progress of the in-app sign-in window.

    status is one of: idle, opening, waiting, success, failed, cancelled.
    """

    status: str
    detail: str
    elapsed_seconds: int = 0
