"""Live verification of the stored DeepSeek session.

session_status() in session.py only inspects the file — it reports "connected"
whenever cookies and a userToken are present. But those expire, so the UI could
show green while every extraction silently fell back. This actually loads
chat.deepseek.com with the shared profile and looks for the composer.

The check costs a headless browser launch (~5-8s), so results are cached. The
cache is invalidated the moment a sign-in succeeds, so the status flips
immediately rather than after the TTL.
"""

import asyncio
import re
import time
from typing import Any

from .errors import DeepSeekAuthError
from .session import DEEPSEEK_ORIGIN, USER_TOKEN_KEY, build_storage_state

# Matches an open tab against chat.deepseek.com, for the live shared-window
# check in verify_session().
_TAB_PATTERN = re.compile(r"deepseek\.com")

# Long enough that opening Settings repeatedly doesn't launch a browser each
# time; short enough that an expiry is noticed within a working session.
CACHE_TTL_SECONDS = 300.0

# How long a probe or sign-out waits for the profile lock before reporting
# busy instead of hanging. A stuck separate-window sign-in, a crashed browser
# that never released its lock, or an extraction in progress are all real
# things that can hold this — the honest answer is "busy", not a frozen card.
PROFILE_LOCK_TIMEOUT_S = 6.0

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


def _is_signed_in(page: Any) -> bool:
    return page.locator(CHAT_INPUT_SELECTOR).count() > 0


def _probe_sync() -> dict[str, Any]:
    """Load DeepSeek in the persistent profile and report whether it still works."""
    from app.services.deepseek import browser as browser_mod

    with browser_mod.browser_context(headless=True, lock_timeout=PROFILE_LOCK_TIMEOUT_S) as context:
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
            if _is_signed_in(page):
                break
            page.wait_for_timeout(400)

        if any(marker in page.url for marker in LOGIN_URL_MARKERS):
            return {
                "connected": False,
                "detail": "The DeepSeek session has expired. Sign in again.",
                "verified": True,
            }
        if not _is_signed_in(page):
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


class SignOutBlocked(RuntimeError):
    """The profile is in use, so it cannot be deleted right now."""


def sign_out() -> dict[str, Any]:
    """Forget the stored DeepSeek session on this machine.

    Deletes the browser profile and the storage-state snapshot — both, because
    either one alone would let the next check report a session that the other
    half no longer backs.

    This signs out of the app, not out of DeepSeek: the account is untouched and
    any session in the user's own browser keeps working.
    """
    import re

    from app.services.deepseek import browser as browser_mod
    from app.services.deepseek.session import DEFAULT_SESSION_PATH

    try:
        browser_mod.clear_origin_cookies(
            re.compile(r"deepseek"), lock_timeout=PROFILE_LOCK_TIMEOUT_S
        )
    except browser_mod.ProfileBusy as exc:
        raise SignOutBlocked(str(exc)) from exc

    # The legacy snapshot file predates the shared profile; delete it too so it
    # cannot be read as a stale fallback session by anything that still checks it.
    DEFAULT_SESSION_PATH.unlink(missing_ok=True)
    invalidate()
    return {
        "connected": False,
        "detail": "Signed out. Sign in again when you need DeepSeek.",
        "verified": True,
        "cached": False,
        "signingIn": False,
    }


async def verify_session(force: bool = False) -> dict[str, Any]:
    """Whether the stored session actually works right now.

    `verified: False` means the answer came from file inspection alone (either
    there is no session, or a cached live result was unavailable).
    """
    # If the shared sign-in window is open with a DeepSeek tab, read it
    # directly rather than launching a second, competing instance against the
    # same profile — that would just queue behind the lock the open window
    # already holds, so a sign-in the user just finished would never be seen
    # until they closed the window.
    from app.services.shared_browser import shared_browser

    live = shared_browser.check_page(_TAB_PATTERN, _is_signed_in)
    if live is True:
        invalidate()
        return {
            "connected": True,
            "detail": "Signed in to DeepSeek.",
            "verified": True,
            "cached": False,
            "signingIn": False,
        }
    if live is False:
        return {
            "connected": False,
            "detail": "Waiting for you to sign in…",
            "verified": True,
            "cached": False,
            "signingIn": True,
        }

    # The window is open, just not on a DeepSeek tab -- launching a second
    # instance against the same profile would only queue behind the lock the
    # open window already holds until it closes, which is what turned "Not
    # connected" into a several-second "browser is in use" error while a
    # different provider's sign-in was up. Answer from the last probe instead
    # of waiting on a lock that will not free up until that window closes.
    if shared_browser.is_open():
        cached = _cache["result"]
        if cached is not None:
            return {**cached, "cached": True, "signingIn": False}
        return {
            "connected": False,
            "detail": "Checking will resume once the sign-in window is free.",
            "verified": False,
            "cached": False,
            "signingIn": False,
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

        from app.services.deepseek import browser as browser_mod

        try:
            result = await asyncio.to_thread(_probe_sync)
        except browser_mod.ProfileBusy as exc:
            # Transient, not a verdict about the session — the shared sign-in
            # window or an extraction could be holding the profile. Caching
            # this would show "busy" for CACHE_TTL_SECONDS after the
            # contention clears, so it deliberately skips the cache.
            return {
                "connected": False,
                "detail": str(exc),
                "verified": False,
                "cached": False,
                "signingIn": True,
            }
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
