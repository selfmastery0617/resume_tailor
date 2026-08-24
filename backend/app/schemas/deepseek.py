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
    # True when a sign-in is holding the browser profile, so "not connected" is
    # "cannot tell yet" rather than a verdict. The UI re-asks instead of
    # settling on the amber answer.
    signingIn: bool = False
