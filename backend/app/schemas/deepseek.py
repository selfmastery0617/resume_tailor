from pydantic import BaseModel


class SessionStatusResponse(BaseModel):
    """Whether a usable DeepSeek session exists right now."""

    connected: bool
    detail: str
    # True when the answer came from actually loading DeepSeek, rather than
    # from inspecting the stored file alone.
    verified: bool = False
    # True when served from the liveness cache rather than a fresh probe.
    cached: bool = False


class LoginStatusResponse(BaseModel):
    """Progress of the in-app sign-in window.

    status is one of: idle, opening, waiting, success, failed, cancelled.
    """

    status: str
    detail: str
    elapsed_seconds: int = 0
