"""The one shared sign-in window.

Every provider's "sign in" button routes through here: it opens (launching the
window on the first call) a new tab at that provider's origin, in the same
window every other provider shares.
"""

import asyncio
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.services.shared_browser import shared_browser

router = APIRouter(prefix="/api/browser", tags=["browser"])

# Origin and a pattern that identifies an already-open tab for it, so a second
# click on the same provider refocuses that tab instead of opening another.
_PROVIDERS: dict[str, tuple[str, re.Pattern[str]]] = {
    "deepseek": ("https://chat.deepseek.com", re.compile(r"deepseek\.com")),
    "chatgpt": ("https://chatgpt.com", re.compile(r"chatgpt\.com|openai\.com")),
    "jobright": ("https://jobright.ai/?login=true", re.compile(r"jobright\.ai")),
}


class OpenTabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str


@router.post("/open-tab")
async def open_tab(payload: OpenTabRequest):
    target = _PROVIDERS.get(payload.provider)
    if target is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "UNKNOWN_PROVIDER", "message": f"Unknown provider: {payload.provider!r}"},
        )
    origin, match = target
    try:
        await asyncio.to_thread(shared_browser.open_tab, origin, match)
    except Exception as exc:  # noqa: BLE001 - surfaced to the dialog verbatim
        raise HTTPException(
            status_code=502,
            detail={"code": "OPEN_TAB_FAILED", "message": str(exc)},
        ) from exc
    return {"ok": True}
