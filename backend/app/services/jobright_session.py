"""The Jobright session: checking it, and signing out.

Jobright's feed is an internal endpoint authenticated with a plain `Cookie`
header, so unlike DeepSeek/ChatGPT this never needs to launch a browser just
to check the session — one HTTP request answers it. The cookie itself is
harvested out of the shared browser (see shared_browser.py) opportunistically:
whenever a status check runs while that window happens to be open, it looks
for Jobright's auth cookie and saves it to secrets/jobright_session.json the
moment it appears. JOBRIGHT_COOKIE still works as a manual fallback, so an
existing setup keeps running untouched.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SESSION_PATH = BACKEND_ROOT / "secrets" / "jobright_session.json"

JOBRIGHT_ORIGIN = "https://jobright.ai"
JOBRIGHT_SIGN_IN_URL = "https://jobright.ai/?login=true"
COOKIE_DOMAIN = re.compile(r"jobright")

# Cookies that only exist once Jobright has authenticated the browser. Without
# one of these the profile holds nothing but anonymous analytics cookies, and
# treating that as a session is what produced "connected" cards that failed on
# the first request.
AUTH_COOKIE_NAMES = ("sessionId", "SESSION", "JSESSIONID", "token", "jwt")

# The verdict is cached briefly so opening Settings repeatedly does not hit
# Jobright each time. Much shorter than DeepSeek's: this probe is cheap.
CACHE_TTL_SECONDS = 60.0
PROBE_TIMEOUT_S = 12.0

_cache: dict[str, Any] = {"checked_at": 0.0, "result": None}
_lock = threading.Lock()


class SignOutBlocked(RuntimeError):
    """The profile is in use, so it cannot be cleared right now."""


# -- the stored cookie ----------------------------------------------------


def _cookie_header(cookies: list[dict[str, Any]]) -> str:
    """Build a Cookie header from Playwright's cookie list."""
    parts = [f"{c['name']}={c['value']}" for c in cookies]
    return "; ".join(parts)


def _save(cookies: list[dict[str, Any]]) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(
        json.dumps(
            {
                "cookie": _cookie_header(cookies),
                "names": sorted({c["name"] for c in cookies}),
                "savedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    invalidate()


def _try_harvest_from_shared_window() -> None:
    """Pick up a freshly-signed-in cookie from the shared browser, if it has
    one right now. A no-op whenever that window isn't open — cheap, since it
    is then just one is_open() check, not a browser launch."""
    from app.services.shared_browser import shared_browser

    cookies = shared_browser.cookies_for(COOKIE_DOMAIN)
    if not cookies or not any(c.get("name") in AUTH_COOKIE_NAMES for c in cookies):
        return  # window not open, or open but not signed in to Jobright yet
    header = _cookie_header(cookies)
    if header and header != stored_cookie():
        _save(cookies)


def stored_cookie() -> str | None:
    """The cookie header from a harvested sign-in, if there is one."""
    if not SESSION_PATH.exists():
        return None
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    cookie = (data.get("cookie") or "").strip()
    return cookie or None


def is_signed_in(page: Any) -> bool:
    """Whether the browser has authenticated with Jobright.

    Reads the browser's own cookies rather than the page's markup: Jobright's
    layout changes, but a session cookie is a session cookie.
    """
    cookies = page.context.cookies(JOBRIGHT_ORIGIN)
    names = {c.get("name") for c in cookies}
    return any(name in names for name in AUTH_COOKIE_NAMES)


# -- status ---------------------------------------------------------------


def invalidate() -> None:
    """Drop the cached verdict, e.g. straight after a sign-in or sign-out."""
    _cache["checked_at"] = 0.0
    _cache["result"] = None


def _probe(cookie: str) -> dict[str, Any]:
    """Ask the feed for one job. Cheaper and truer than inspecting the file."""
    from app.services.jobright_client import (
        JOBRIGHT_BASE_URL,
        JOBRIGHT_JOBS_PATH,
        _build_headers,
    )

    try:
        with httpx.Client(base_url=JOBRIGHT_BASE_URL, timeout=PROBE_TIMEOUT_S) as client:
            response = client.get(
                JOBRIGHT_JOBS_PATH,
                params={
                    "refresh": "false",
                    "sortCondition": 2,
                    "position": 0,
                    "count": 1,
                    "syncRerank": "false",
                },
                headers=_build_headers(cookie),
            )
    except httpx.HTTPError as exc:
        return {
            "connected": False,
            "detail": f"Could not reach Jobright to check the session ({type(exc).__name__}).",
            "verified": False,
        }

    if response.status_code in (401, 403):
        return {
            "connected": False,
            "detail": "The Jobright session has expired. Sign in again.",
            "verified": True,
        }
    if response.status_code >= 400:
        return {
            "connected": False,
            "detail": f"Jobright answered {response.status_code}. Sign in again.",
            "verified": True,
        }

    # A 200 with an error code in the body is Jobright's way of saying "not
    # authenticated" — the status line alone would read as success.
    try:
        body = response.json()
    except ValueError:
        return {
            "connected": False,
            "detail": "Jobright returned something unreadable. Sign in again.",
            "verified": True,
        }
    if str(body.get("code", 0)) not in ("0", "200", "None"):
        return {
            "connected": False,
            "detail": f"Jobright rejected the session: {body.get('message') or body.get('code')}.",
            "verified": True,
        }
    return {"connected": True, "detail": "Signed in to Jobright.", "verified": True}


def verify_session(force: bool = False) -> dict[str, Any]:
    """Whether the stored Jobright session actually works right now."""
    _try_harvest_from_shared_window()

    import os

    cookie = stored_cookie() or (os.getenv("JOBRIGHT_COOKIE") or "").strip()
    if not cookie:
        invalidate()
        return {
            "connected": False,
            "detail": "Not signed in to Jobright. Importing jobs needs a session.",
            "verified": False,
            "cached": False,
            "signingIn": False,
        }

    with _lock:
        cached = _cache["result"]
        fresh = time.monotonic() - _cache["checked_at"] < CACHE_TTL_SECONDS
        if cached is not None and fresh and not force:
            return {**cached, "cached": True, "signingIn": False}

        result = _probe(cookie)
        _cache["result"] = result
        _cache["checked_at"] = time.monotonic()
        return {**result, "cached": False, "signingIn": False}


# -- sign out -------------------------------------------------------------


def sign_out() -> dict[str, Any]:
    """Forget Jobright's cookies from the shared profile and the harvested
    copy on disk. Origin-scoped, not a directory delete: the profile also
    holds DeepSeek's and ChatGPT's sessions. Signs out of the app, not out of
    Jobright — the account is untouched.
    """
    from app.services.deepseek import browser as browser_mod
    from app.services.deepseek.browser import PROFILE_DIR

    try:
        browser_mod.clear_origin_cookies(COOKIE_DOMAIN, PROFILE_DIR, lock_timeout=6.0)
    except browser_mod.ProfileBusy as exc:
        raise SignOutBlocked(str(exc)) from exc

    SESSION_PATH.unlink(missing_ok=True)
    invalidate()

    import os

    detail = "Signed out. Sign in again when you need to import jobs."
    if (os.getenv("JOBRIGHT_COOKIE") or "").strip():
        # Otherwise the card would flip straight back to green and look broken.
        detail += " JOBRIGHT_COOKIE is still set in backend/.env and will be used instead."
    return {
        "connected": False,
        "detail": detail,
        "verified": True,
        "cached": False,
        "signingIn": False,
    }
