from fastapi import APIRouter, HTTPException

from app.schemas.deepseek import SessionStatusResponse
from app.services import chatgpt_pool, chatgpt_session

router = APIRouter(prefix="/api/chatgpt", tags=["chatgpt"])


def _resolve(worker: int):
    return chatgpt_pool.get_worker(worker).profile_dir


@router.get("/workers")
def list_workers():
    """Every currently configured worker index -- drives the Settings page's
    one-connect-card-per-worker section."""
    return [{"index": w.index} for w in chatgpt_pool.workers()]


@router.get("/session", response_model=SessionStatusResponse)
async def get_session(worker: int = 1, force: bool = False):
    """Whether the stored session for `worker` actually works right now.

    Loads ChatGPT with that worker's own profile rather than only inspecting
    a file, so an expired session reports "not connected" instead of showing
    green.
    """
    return SessionStatusResponse(
        **await chatgpt_session.verify_session(profile_dir=_resolve(worker), force=force)
    )


@router.post("/sign-out", response_model=SessionStatusResponse)
def sign_out(worker: int = 1):
    """Forget the stored session for `worker`. Signs out of the app, not out
    of ChatGPT."""
    try:
        return SessionStatusResponse(**chatgpt_session.sign_out(profile_dir=_resolve(worker)))
    except chatgpt_session.SignOutBlocked as exc:
        raise HTTPException(
            status_code=409, detail={"code": "SIGN_OUT_BLOCKED", "message": str(exc)}
        ) from exc
