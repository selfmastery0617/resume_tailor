"""The ChatGPT session: checking it, and signing out.

Lives in the one profile shared with DeepSeek and Jobright — see
deepseek/browser.py. Checking is a live probe rather than a file inspection:
cookies expire, and a card that reads "Connected" on the strength of a file on
disk is exactly how a session goes stale without anyone noticing.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from app.services.chatgpt import (
    CHATGPT_ORIGIN,
    COMPOSER_SELECTOR,
    PROFILE_DIR,
    has_session_cookie,
    is_signed_in,
)

# A browser launch costs several seconds, so the verdict is cached. Same TTL as
# DeepSeek's: long enough that reopening Settings is free, short enough that an
# expiry is noticed within a working session.
CACHE_TTL_SECONDS = 300.0
# How long a probe or sign-out waits for the profile lock before reporting
# busy instead of hanging — see the note in deepseek/browser.py.
PROFILE_LOCK_TIMEOUT_S = 6.0
PROBE_TIMEOUT_MS = 25_000
SETTLE_TIMEOUT_S = 12.0
LOGIN_URL_MARKERS = ("/auth/login", "/log-in", "auth.openai.com")

# Matches both chatgpt.com and the auth.openai.com hop it redirects through.
COOKIE_DOMAIN = re.compile(r"chatgpt\.com|openai\.com")
_TAB_PATTERN = re.compile(r"chatgpt\.com|openai\.com")

_cache: dict[str, Any] = {"checked_at": 0.0, "result": None}
_lock = asyncio.Lock()


class SignOutBlocked(RuntimeError):
    """The profile is in use, so it cannot be cleared right now."""


def _diagnose_live_page(page: Any) -> dict[str, Any]:
    """Same check as is_signed_in(), but reports which half failed.

    Temporary-ish debugging aid: "not connected" alone doesn't say whether the
    session cookie never showed up or the composer just hasn't rendered yet,
    and those point at very different problems.
    """
    has_cookie = has_session_cookie(page)
    composer_count = page.locator(COMPOSER_SELECTOR).count()
    return {
        "signed_in": has_cookie and composer_count > 0,
        "has_cookie": has_cookie,
        "composer_count": composer_count,
        "url": page.url,
    }


def invalidate() -> None:
    """Drop the cached verdict, e.g. straight after a sign-in or sign-out."""
    _cache["checked_at"] = 0.0
    _cache["result"] = None


def _probe_sync() -> dict[str, Any]:
    """Load ChatGPT in the shared profile and report whether it still works."""
    from app.services.deepseek import browser as browser_mod

    with browser_mod.browser_context(
        headless=True, profile_dir=PROFILE_DIR, lock_timeout=PROFILE_LOCK_TIMEOUT_S
    ) as context:
        page = browser_mod.first_page(context)
        # domcontentloaded, not "load": ChatGPT holds connections open, so
        # waiting for every resource to settle times out on a usable page.
        page.goto(CHATGPT_ORIGIN, timeout=PROBE_TIMEOUT_MS, wait_until="domcontentloaded")

        deadline = time.monotonic() + SETTLE_TIMEOUT_S
        while time.monotonic() < deadline:
            if any(marker in page.url for marker in LOGIN_URL_MARKERS):
                break
            if is_signed_in(page):
                break
            page.wait_for_timeout(400)

        if any(marker in page.url for marker in LOGIN_URL_MARKERS):
            return {
                "connected": False,
                "detail": "The ChatGPT session has expired. Sign in again.",
                "verified": True,
            }
        if not is_signed_in(page):
            return {
                "connected": False,
                "detail": (
                    "ChatGPT did not load a signed-in page — the session has expired, "
                    "or a Cloudflare check is blocking access. Sign in again."
                ),
                "verified": True,
            }
        return {"connected": True, "detail": "Signed in to ChatGPT.", "verified": True}


async def verify_session(force: bool = False) -> dict[str, Any]:
    """Whether the stored ChatGPT session actually works right now."""
    from app.services.deepseek import browser as browser_mod

    # If the shared sign-in window is open with a ChatGPT tab, read it
    # directly rather than launching a second, competing instance against the
    # same profile — that would just queue behind the lock the open window
    # already holds, so a sign-in the user just finished would never be seen
    # until they closed the window.
    from app.services.shared_browser import shared_browser

    live = shared_browser.check_page(_TAB_PATTERN, _diagnose_live_page)
    if live is not None:
        if live["signed_in"]:
            invalidate()
            return {
                "connected": True,
                "detail": "Signed in to ChatGPT.",
                "verified": True,
                "cached": False,
                "signingIn": False,
            }
        detail = (
            "Session cookie is set, but the chat composer hasn't appeared on "
            f"the page yet (still on {live['url']})."
            if live["has_cookie"]
            else "Waiting for you to sign in…"
        )
        return {
            "connected": False,
            "detail": detail,
            "verified": True,
            "cached": False,
            "signingIn": True,
        }

    # The window is open, just not on a ChatGPT tab -- launching a second
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

    # An empty shared profile means nothing is signed in to anything, so there
    # is no point paying for a browser launch just to confirm that.
    if not browser_mod.profile_exists(PROFILE_DIR):
        invalidate()
        return {
            "connected": False,
            "detail": "Not signed in to ChatGPT.",
            "verified": False,
            "cached": False,
            "signingIn": False,
        }

    async with _lock:
        cached = _cache["result"]
        fresh = time.monotonic() - _cache["checked_at"] < CACHE_TTL_SECONDS
        if cached is not None and fresh and not force:
            return {**cached, "cached": True, "signingIn": False}

        try:
            result = await asyncio.to_thread(_probe_sync)
        except browser_mod.ProfileBusy as exc:
            # Transient, not a verdict — the shared sign-in window or an
            # extraction has the profile right now. Skip the cache so the next
            # check retries instead of showing "busy" for CACHE_TTL_SECONDS.
            return {
                "connected": False,
                "detail": str(exc),
                "verified": False,
                "cached": False,
                "signingIn": True,
            }
        except Exception as exc:  # noqa: BLE001 - a probe must never 500 the page
            reason = type(exc).__name__
            result = {
                "connected": False,
                "detail": (
                    "Could not reach ChatGPT to verify the session — check your "
                    "internet connection, then sign in again."
                    if "Timeout" in reason
                    else "Could not verify the ChatGPT session. Sign in again."
                ),
                "verified": False,
            }

        _cache["result"] = result
        _cache["checked_at"] = time.monotonic()
        return {**result, "cached": False, "signingIn": False}


def sign_out() -> dict[str, Any]:
    """Forget ChatGPT's cookies from the shared profile.

    Origin-scoped, not a directory delete: the profile also holds DeepSeek's
    and Jobright's sessions, so wiping the whole thing would sign them out too.
    Signs out of the app, not out of ChatGPT — the account is untouched.
    """
    from app.services.deepseek import browser as browser_mod

    try:
        browser_mod.clear_origin_cookies(
            COOKIE_DOMAIN, PROFILE_DIR, lock_timeout=PROFILE_LOCK_TIMEOUT_S
        )
    except browser_mod.ProfileBusy as exc:
        raise SignOutBlocked(str(exc)) from exc

    invalidate()
    return {
        "connected": False,
        "detail": "Signed out. Sign in again when you need ChatGPT.",
        "verified": True,
        "cached": False,
        "signingIn": False,
    }
