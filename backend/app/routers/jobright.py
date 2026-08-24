from fastapi import APIRouter, HTTPException

from app.schemas.deepseek import SessionStatusResponse
from app.services import jobright_session

router = APIRouter(prefix="/api/jobright", tags=["jobright"])


@router.get("/session", response_model=SessionStatusResponse)
async def get_session(force: bool = False):
    """Whether the stored Jobright cookie still works.

    One HTTP request to the feed rather than a browser launch — cheap enough
    to run off the event loop without a thread pool, but still a live check.
    """
    import asyncio

    return SessionStatusResponse(
        **await asyncio.to_thread(jobright_session.verify_session, force)
    )


@router.post("/sign-out", response_model=SessionStatusResponse)
def sign_out():
    """Forget the stored session. Signs out of the app, not out of Jobright."""
    try:
        return SessionStatusResponse(**jobright_session.sign_out())
    except jobright_session.SignOutBlocked as exc:
        raise HTTPException(
            status_code=409, detail={"code": "SIGN_OUT_BLOCKED", "message": str(exc)}
        ) from exc
