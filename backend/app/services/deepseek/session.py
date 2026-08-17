"""Loading and normalizing a logged-in DeepSeek browser session.

DeepSeek's web app keeps its bearer credential in **localStorage** under
`userToken` — cookies alone are not enough to stay logged in. Everything here
normalizes whatever the user exported (Playwright storage state, a
Cookie-Editor JSON dump, or a raw cookie header string) into the single
Playwright `storage_state` shape that carries both cookies and localStorage.
"""

import json
import os
from pathlib import Path
from typing import Any

from .errors import DeepSeekAuthError

DEEPSEEK_ORIGIN = "https://chat.deepseek.com"
DEEPSEEK_COOKIE_DOMAIN = ".deepseek.com"

# backend/ — session.py lives at backend/app/services/deepseek/session.py.
# Relative session paths resolve against this, not the process cwd, so the
# same .env works whether uvicorn is launched from backend/ or from the
# project root with --app-dir backend.
BACKEND_ROOT = Path(__file__).resolve().parents[3]

# Where the in-app login flow writes the captured session. Used automatically
# when no DEEPSEEK_* env source is configured, so logging in through the UI
# just works without anyone editing .env.
DEFAULT_SESSION_PATH = BACKEND_ROOT / "secrets" / "deepseek_session.json"

# localStorage key holding the web app's bearer token.
USER_TOKEN_KEY = "userToken"

# Cookie-Editor / EditThisCookie use Chrome's sameSite vocabulary; Playwright
# only accepts these three exact values.
_SAME_SITE_MAP = {
    "lax": "Lax",
    "strict": "Strict",
    "none": "None",
    "no_restriction": "None",
    "unspecified": "Lax",
}


def _normalize_cookie(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = raw.get("name")
    value = raw.get("value")
    if not name or value is None:
        return None

    cookie: dict[str, Any] = {
        "name": name,
        "value": str(value),
        "domain": raw.get("domain") or DEEPSEEK_COOKIE_DOMAIN,
        "path": raw.get("path") or "/",
        "httpOnly": bool(raw.get("httpOnly", False)),
        "secure": bool(raw.get("secure", True)),
        "sameSite": _SAME_SITE_MAP.get(str(raw.get("sameSite", "lax")).lower(), "Lax"),
    }

    # Chrome exports use `expirationDate` (float seconds); Playwright wants
    # `expires`. Session cookies (no expiry) are left out entirely.
    expires = raw.get("expires", raw.get("expirationDate"))
    if expires is not None:
        try:
            cookie["expires"] = int(float(expires))
        except (TypeError, ValueError):
            pass

    return cookie


def _cookies_from_header_string(cookie_header: str) -> list[dict[str, Any]]:
    """Parse a raw `a=1; b=2` Cookie header (what DevTools -> copy gives you)."""
    cookies: list[dict[str, Any]] = []
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies.append(
            {
                "name": name.strip(),
                "value": value.strip(),
                "domain": DEEPSEEK_COOKIE_DOMAIN,
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            }
        )
    return cookies


def _resolve_path(raw: str) -> Path:
    """Absolute paths pass through; relative ones anchor to backend/."""
    path = Path(raw)
    return path if path.is_absolute() else BACKEND_ROOT / path


def _read_json_file(path: Path) -> Any:
    try:
        # utf-8-sig transparently strips the BOM that Notepad / PowerShell
        # Out-File add, which plain utf-8 would choke on.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise DeepSeekAuthError(f"DeepSeek session file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DeepSeekAuthError(f"DeepSeek session file is not valid JSON: {path}") from exc


def build_storage_state(
    storage_state_path: str | None = None,
    cookie_file_path: str | None = None,
    cookie_header: str | None = None,
    user_token: str | None = None,
) -> dict[str, Any]:
    """Assemble a Playwright storage_state from whichever session source is set.

    Precedence: explicit storage-state file > cookie file > raw cookie header.
    A `user_token` from any source is merged into localStorage on top.
    """
    storage_state_path = storage_state_path or os.getenv("DEEPSEEK_STORAGE_STATE")
    cookie_file_path = cookie_file_path or os.getenv("DEEPSEEK_COOKIE_FILE")
    cookie_header = cookie_header or os.getenv("DEEPSEEK_COOKIES")
    user_token = user_token or os.getenv("DEEPSEEK_USER_TOKEN")

    # Nothing configured explicitly: fall back to whatever the in-app login
    # flow captured, so signing in through the UI is enough on its own.
    if not any((storage_state_path, cookie_file_path, cookie_header, user_token)):
        if DEFAULT_SESSION_PATH.exists():
            storage_state_path = str(DEFAULT_SESSION_PATH)

    cookies: list[dict[str, Any]] = []
    local_storage: list[dict[str, str]] = []

    if storage_state_path:
        data = _read_json_file(_resolve_path(storage_state_path))
        if not isinstance(data, dict):
            raise DeepSeekAuthError(
                f"DEEPSEEK_STORAGE_STATE must contain a Playwright storage-state "
                f"object, got {type(data).__name__}: {storage_state_path}"
            )
        # Already in Playwright shape — normalize cookies defensively and keep
        # whatever localStorage the export captured.
        for raw in data.get("cookies", []) or []:
            normalized = _normalize_cookie(raw)
            if normalized:
                cookies.append(normalized)
        for origin in data.get("origins", []) or []:
            if origin.get("origin", "").rstrip("/") == DEEPSEEK_ORIGIN:
                local_storage.extend(origin.get("localStorage", []) or [])

    elif cookie_file_path:
        data = _read_json_file(_resolve_path(cookie_file_path))
        # Cookie-Editor exports a bare array; some tools wrap it in {"cookies": [...]}.
        raw_cookies = data.get("cookies", []) if isinstance(data, dict) else data
        if not isinstance(raw_cookies, list):
            raise DeepSeekAuthError(
                f"DEEPSEEK_COOKIE_FILE must contain a cookie array: {cookie_file_path}"
            )
        for raw in raw_cookies:
            normalized = _normalize_cookie(raw)
            if normalized:
                cookies.append(normalized)

    elif cookie_header:
        cookies = _cookies_from_header_string(cookie_header)

    if user_token:
        # Explicit token wins over anything captured in the export.
        local_storage = [item for item in local_storage if item.get("name") != USER_TOKEN_KEY]
        local_storage.append({"name": USER_TOKEN_KEY, "value": user_token})

    if not cookies and not local_storage:
        raise DeepSeekAuthError(
            "Not signed in to DeepSeek. Use the Connect DeepSeek button in the "
            "app to sign in, or configure DEEPSEEK_STORAGE_STATE / "
            "DEEPSEEK_COOKIE_FILE / DEEPSEEK_COOKIES in backend/.env "
            "(see docs/deepseek-session.md)."
        )

    state: dict[str, Any] = {"cookies": cookies, "origins": []}
    if local_storage:
        state["origins"].append({"origin": DEEPSEEK_ORIGIN, "localStorage": local_storage})
    return state


def session_status() -> dict[str, Any]:
    """Describe the currently usable session, for the frontend's status chip."""
    try:
        state = build_storage_state()
    except DeepSeekAuthError as exc:
        return {"connected": False, "detail": str(exc)}

    has_token = any(
        item.get("name") == USER_TOKEN_KEY
        for origin in state.get("origins", [])
        for item in origin.get("localStorage", [])
    )
    if not has_token:
        return {
            "connected": False,
            "detail": (
                "A session was found but it has no userToken, which DeepSeek "
                "authenticates with. Sign in again to capture a complete session."
            ),
        }

    return {"connected": True, "detail": "Signed in to DeepSeek."}
