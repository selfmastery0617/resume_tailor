"""Reusable in-app browser sign-in.

Generalises the flow proven by the DeepSeek integration: open a real, visible
Chromium window, wait for the user to finish signing in (including captcha or
Cloudflare steps), then persist cookies + localStorage as a Playwright
storage-state file.

Why a separate window rather than an iframe: these providers refuse to be
framed, and cookies set in the user's own browser aren't reachable from this
backend. The window Playwright opens *is* reachable, which is what makes the
captured session usable later.

The DeepSeek implementation in services/deepseek/login.py predates this and is
intentionally left alone; new providers use this instead.
"""

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

LoginStatus = Literal["idle", "opening", "waiting", "success", "failed", "cancelled"]

LOGIN_TIMEOUT_S = 600.0
POLL_INTERVAL_S = 1.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)


@dataclass
class ProviderConfig:
    """Everything provider-specific about signing in."""

    key: str
    label: str
    origin: str
    session_path: Path
    # Returns True once the page shows a signed-in state. Runs in the browser
    # thread with a sync Playwright `page`.
    is_signed_in: Callable[[Any], bool]
    # Names of cookies/localStorage keys that must be present for the saved
    # session to be considered complete.
    required_cookie: str | None = None
    required_local_storage_key: str | None = None


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


class BrowserLoginManager:
    """One sign-in flow per provider."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._state = _LoginState()
        self._task: asyncio.Task[None] | None = None

    # -- status ----------------------------------------------------------

    def login_status(self) -> dict[str, Any]:
        return self._state.snapshot()

    def is_running(self) -> bool:
        return self._state.status in ("opening", "waiting")

    def session_status(self) -> dict[str, Any]:
        """Whether a usable saved session exists right now."""
        path = self.config.session_path
        if not path.exists():
            return {
                "connected": False,
                "detail": f"Not signed in to {self.config.label}.",
            }
        try:
            state = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {
                "connected": False,
                "detail": f"The saved {self.config.label} session is unreadable. Sign in again.",
            }

        cookies = state.get("cookies") or []
        if self.config.required_cookie and not any(
            c.get("name") == self.config.required_cookie for c in cookies
        ):
            return {
                "connected": False,
                "detail": (
                    f"The saved {self.config.label} session is missing its auth cookie. "
                    "Sign in again."
                ),
            }

        if self.config.required_local_storage_key:
            keys = {
                item.get("name")
                for origin in state.get("origins", []) or []
                for item in origin.get("localStorage", []) or []
            }
            if self.config.required_local_storage_key not in keys:
                return {
                    "connected": False,
                    "detail": (
                        f"The saved {self.config.label} session is incomplete. Sign in again."
                    ),
                }

        if not cookies and not state.get("origins"):
            return {"connected": False, "detail": f"Not signed in to {self.config.label}."}

        return {"connected": True, "detail": f"Signed in to {self.config.label}."}

    def sign_out(self) -> None:
        """Forget the saved session (does not touch the provider account)."""
        self.config.session_path.unlink(missing_ok=True)
        self._state.set("idle", "Not started.")

    # -- login -----------------------------------------------------------

    async def start_login(self) -> dict[str, Any]:
        if self.is_running():
            return self._state.snapshot()

        self._state.started_at = time.monotonic()
        self._state.set("opening", f"Opening the {self.config.label} sign-in window...")
        # Playwright's sync api needs a thread with no running event loop; see
        # the note in DeepSeekService.ask().
        self._task = asyncio.create_task(asyncio.to_thread(self._run_login_sync))
        return self._state.snapshot()

    def _run_login_sync(self) -> None:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=False,  # the point: the user must see and use it
                    args=["--disable-blink-features=AutomationControlled"],
                )
                try:
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 900}, user_agent=USER_AGENT
                    )
                    page = context.new_page()
                    page.goto(self.config.origin, timeout=60_000)
                    self._state.set(
                        "waiting",
                        f"Sign in to {self.config.label} in the window that just opened. "
                        "This page updates automatically once you're done.",
                    )

                    deadline = time.monotonic() + LOGIN_TIMEOUT_S
                    while True:
                        if time.monotonic() > deadline:
                            self._state.set(
                                "failed",
                                "Timed out waiting for sign-in. Close the window and try again.",
                            )
                            return

                        if page.is_closed() or not context.pages:
                            self._state.set(
                                "cancelled", "Sign-in window was closed before finishing."
                            )
                            return

                        try:
                            signed_in = self.config.is_signed_in(page)
                        except PlaywrightError:
                            signed_in = False  # mid-navigation; retry

                        if signed_in:
                            self.config.session_path.parent.mkdir(parents=True, exist_ok=True)
                            context.storage_state(path=str(self.config.session_path))
                            self._state.set(
                                "success",
                                f"Signed in to {self.config.label}. You can close the window.",
                            )
                            return

                        time.sleep(POLL_INTERVAL_S)
                finally:
                    # Always close, on every exit path.
                    browser.close()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
            self._state.set("failed", f"Sign-in failed: {exc}")
