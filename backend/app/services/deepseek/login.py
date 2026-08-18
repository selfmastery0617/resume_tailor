"""In-app DeepSeek sign-in.

Opens a real, visible Chromium window pointed at chat.deepseek.com, waits for
the user to finish signing in (including any Cloudflare/captcha step), then
saves the resulting cookies + localStorage to DEFAULT_SESSION_PATH.

Why a separate window rather than an iframe in the React app: DeepSeek refuses
to be framed, and even if it didn't, cookies set inside the user's own browser
are not reachable by this backend. The window Playwright opens *is* reachable,
which is what makes the captured session usable for extraction.

The flow is long-running (a person has to type), so it runs as a background
task and the frontend polls get_login_status().
"""

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from .session import DEEPSEEK_ORIGIN, DEFAULT_SESSION_PATH, USER_TOKEN_KEY

LoginStatus = Literal["idle", "opening", "waiting", "success", "failed", "cancelled"]

# DeepSeek writes a `userToken` into localStorage as soon as it redirects to its
# own sign-in page — before the user has entered anything. Treating that as
# success closed the window a few seconds after it opened and saved a session
# that was never authenticated. Sign-in is therefore only accepted when all
# three hold: off the login page, the composer rendered, and a token present.
LOGIN_URL_MARKERS = ("/sign_in", "/login")
CHAT_INPUT_SELECTOR = "textarea#chat-input, textarea"

# Consecutive positive polls required before the session is saved.
REQUIRED_CONFIRMATIONS = 2

# How long to leave the sign-in window open before giving up.
LOGIN_TIMEOUT_S = 600.0
POLL_INTERVAL_S = 1.0


@dataclass
class _LoginState:
    status: LoginStatus = "idle"
    detail: str = "Not started."
    started_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set(self, status: LoginStatus, detail: str) -> None:
        with self._lock:
            self.status = status
            self.detail = detail

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed = int(time.monotonic() - self.started_at) if self.started_at else 0
            return {"status": self.status, "detail": self.detail, "elapsed_seconds": elapsed}


_state = _LoginState()
_task: asyncio.Task[None] | None = None


def get_login_status() -> dict[str, Any]:
    return _state.snapshot()


def is_login_running() -> bool:
    return _state.status in ("opening", "waiting")


async def start_login() -> dict[str, Any]:
    """Kick off the sign-in window if one isn't already open."""
    global _task

    if is_login_running():
        return _state.snapshot()

    _state.started_at = time.monotonic()
    _state.set("opening", "Opening the DeepSeek sign-in window...")
    # Same threading rationale as extraction: Playwright's sync api needs a
    # thread with no running event loop. See DeepSeekService.ask().
    _task = asyncio.create_task(asyncio.to_thread(_run_login_sync))
    return _state.snapshot()


def _is_signed_in(page: Any) -> bool:
    """True once DeepSeek is genuinely usable for this session.

    Two signals, deliberately chosen:

    * NOT on the login page — this is what rejects the pre-auth token DeepSeek
      writes the moment it redirects to /sign_in, which used to close the window
      about four seconds after it opened.
    * a userToken present — the credential the app actually authenticates with.

    The composer is treated as a bonus accelerator, not a requirement: DeepSeek
    can land on a chat, an empty state or a campaign page after login, and
    demanding a specific textarea would leave the window open forever on any
    layout that doesn't match.
    """
    from playwright.sync_api import Error as PlaywrightError

    try:
        if any(marker in page.url for marker in LOGIN_URL_MARKERS):
            return False
        token = page.evaluate("key => window.localStorage.getItem(key)", USER_TOKEN_KEY)
        return bool(token)
    except PlaywrightError:
        # Navigating or reloading mid-check; try again on the next tick.
        return False


def _run_login_sync() -> None:
    from app.services.deepseek import browser as browser_mod

    try:
        # Persistent profile: signing in here writes cookies straight into the
        # profile, so nothing has to be snapshotted and the session lasts as
        # long as it naturally would in a normal browser.
        with browser_mod.browser_context(headless=False) as context:
            try:
                page = browser_mod.first_page(context)
                page.goto(DEEPSEEK_ORIGIN, timeout=60_000)
                _state.set(
                    "waiting",
                    "Sign in to DeepSeek in the window that just opened. "
                    "It closes by itself once you're done.",
                )

                deadline = time.monotonic() + LOGIN_TIMEOUT_S
                confirmations = 0
                while True:
                    if time.monotonic() > deadline:
                        _state.set(
                            "failed",
                            "Timed out waiting for sign-in. Try again.",
                        )
                        return

                    # User closed the window -> treat as an explicit cancel.
                    if page.is_closed() or not context.pages:
                        _state.set("cancelled", "Sign-in window was closed before finishing.")
                        return

                    # Require two consecutive positives: the redirect back from
                    # the login form passes through transient states, and
                    # snapshotting during one captures a half-written session.
                    if _is_signed_in(page):
                        confirmations += 1
                    else:
                        confirmations = 0

                    if confirmations >= REQUIRED_CONFIRMATIONS:
                        # Let cookies settle before the context closes and
                        # flushes them into the profile.
                        page.wait_for_timeout(1_500)
                        # Also write a storage-state snapshot, so anything still
                        # reading the old session file keeps working.
                        DEFAULT_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
                        context.storage_state(path=str(DEFAULT_SESSION_PATH))
                        _state.set("success", "Signed in to DeepSeek. Closing the window…")
                        return

                    time.sleep(POLL_INTERVAL_S)
            finally:
                # The context manager closes the browser on every path —
                # success, timeout, cancel, or an unexpected error.
                pass
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
        _state.set("failed", f"Sign-in failed: {exc}")
