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


def _run_login_sync() -> None:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False,  # the whole point: the user must see and use it
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto(DEEPSEEK_ORIGIN, timeout=60_000)
            _state.set(
                "waiting",
                "Sign in to DeepSeek in the window that just opened. "
                "This page updates automatically once you're done.",
            )

            deadline = time.monotonic() + LOGIN_TIMEOUT_S
            while True:
                if time.monotonic() > deadline:
                    _state.set(
                        "failed",
                        "Timed out waiting for sign-in. Close the window and try again.",
                    )
                    browser.close()
                    return

                # User closed the window -> treat as an explicit cancel.
                if page.is_closed() or not context.pages:
                    _state.set("cancelled", "Sign-in window was closed before finishing.")
                    browser.close()
                    return

                try:
                    token = page.evaluate(
                        "key => window.localStorage.getItem(key)", USER_TOKEN_KEY
                    )
                except PlaywrightError:
                    # Navigating/reloading mid-evaluate; just try again.
                    token = None

                if token:
                    DEFAULT_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(DEFAULT_SESSION_PATH))
                    _state.set("success", "Signed in to DeepSeek. You can close the window.")
                    browser.close()
                    return

                time.sleep(POLL_INTERVAL_S)
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
        _state.set("failed", f"Sign-in failed: {exc}")
