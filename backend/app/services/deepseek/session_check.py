"""Live verification of the stored DeepSeek session.

session_status() in session.py only inspects the file — it reports "connected"
whenever cookies and a userToken are present. But those expire, so the UI could
show green while every extraction silently fell back. This actually loads
chat.deepseek.com with the stored session and looks for the composer.

The check costs a headless browser launch (~5-8s), so results are cached. The
cache is invalidated the moment a sign-in succeeds, so the status flips
immediately rather than after the TTL.
"""

import asyncio
import time
from typing import Any

from .errors import DeepSeekAuthError
from .session import DEEPSEEK_ORIGIN, USER_TOKEN_KEY, build_storage_state

# Long enough that opening Settings repeatedly doesn't launch a browser each
# time; short enough that an expiry is noticed within a working session.
CACHE_TTL_SECONDS = 300.0

PROBE_TIMEOUT_MS = 25_000
# How long to wait, after the document loads, for either the composer to render
# or a redirect to the login page.
SETTLE_TIMEOUT_S = 12.0
CHAT_INPUT_SELECTOR = "textarea#chat-input, textarea"
LOGIN_URL_MARKERS = ("/sign_in", "/login")

_cache: dict[str, Any] = {"checked_at": 0.0, "result": None}
_lock = asyncio.Lock()


def _structural_status() -> dict[str, Any] | None:
    """Cheap checks before paying for a browser. None means 'keep going'."""
    from app.services.deepseek import browser as browser_mod

    # With a remote Chrome attached, its own profile is the source of truth.
    if browser_mod.cdp_url():
        return None

    if browser_mod.profile_exists():
        return None

    # No profile yet — fall back to the legacy storage-state file, so a session
    # captured before the profile existed still counts.
    try:
        state = build_storage_state()
    except DeepSeekAuthError:
        return {
            "connected": False,
            "detail": "Not signed in to DeepSeek. Use Connect DeepSeek to sign in.",
            "verified": False,
        }

    has_token = any(
        item.get("name") == USER_TOKEN_KEY
        for origin in state.get("origins", [])
        for item in origin.get("localStorage", [])
    )
    if not has_token:
        return {
            "connected": False,
            "detail": (
                "The saved session has no userToken, which DeepSeek authenticates "
                "with. Sign in again."
            ),
            "verified": False,
        }
    return None


def _probe_sync() -> dict[str, Any]:
    """Load DeepSeek in the persistent profile and report whether it still works."""
    from app.services.deepseek import browser as browser_mod

    with browser_mod.browser_context(headless=True) as context:
        page = browser_mod.first_page(context)
        # domcontentloaded, not the default "load": DeepSeek keeps long-lived
        # connections open, so waiting for every resource to settle times out
        # even when the page is perfectly usable.
        page.goto(DEEPSEEK_ORIGIN, timeout=PROBE_TIMEOUT_MS, wait_until="domcontentloaded")

        # Wait for whichever outcome arrives first: the composer (signed in) or
        # a redirect to the login page (expired).
        deadline = time.monotonic() + SETTLE_TIMEOUT_S
        while time.monotonic() < deadline:
            if any(marker in page.url for marker in LOGIN_URL_MARKERS):
                break
            if page.locator(CHAT_INPUT_SELECTOR).count() > 0:
                break
            page.wait_for_timeout(400)

        if any(marker in page.url for marker in LOGIN_URL_MARKERS):
            return {
                "connected": False,
                "detail": "The DeepSeek session has expired. Sign in again.",
                "verified": True,
            }
        if page.locator(CHAT_INPUT_SELECTOR).count() == 0:
            return {
                "connected": False,
                "detail": (
                    "DeepSeek did not load the chat input — the session has expired, "
                    "or a Cloudflare check is blocking access. Sign in again."
                ),
                "verified": True,
            }
        return {"connected": True, "detail": "Signed in to DeepSeek.", "verified": True}


def invalidate() -> None:
    """Drop the cached result, e.g. straight after a successful sign-in."""
    _cache["checked_at"] = 0.0
    _cache["result"] = None


async def verify_session(force: bool = False) -> dict[str, Any]:
    """Whether the stored session actually works right now.

    `verified: False` means the answer came from file inspection alone (either
    there is no session, or a cached live result was unavailable).
    """
    # An embedded sign-in holds the profile lock; probing now would block until
    # it finishes, hanging the Settings page.
    from app.services.deepseek import embedded_login

    if embedded_login.is_active():
        return {
            "connected": False,
            "detail": "Sign-in in progress…",
            "verified": False,
            "cached": False,
        }

    structural = _structural_status()
    if structural is not None:
        # No point launching a browser when there is nothing to test.
        invalidate()
        return structural

    async with _lock:
        cached = _cache["result"]
        fresh = time.monotonic() - _cache["checked_at"] < CACHE_TTL_SECONDS
        if cached is not None and fresh and not force:
            return {**cached, "cached": True}

        try:
            result = await asyncio.to_thread(_probe_sync)
        except Exception as exc:  # noqa: BLE001 - probe must never 500 the page
            # Playwright errors are multi-line traces; surfacing one verbatim in
            # the UI tells the user nothing they can act on.
            reason = type(exc).__name__
            friendly = (
                "Could not reach DeepSeek to verify the session — check your "
                "internet connection, then sign in again."
                if "Timeout" in reason
                else "Could not verify the DeepSeek session. Sign in again."
            )
            result = {"connected": False, "detail": friendly, "verified": False}

        _cache["result"] = result
        _cache["checked_at"] = time.monotonic()
        return {**result, "cached": False}
