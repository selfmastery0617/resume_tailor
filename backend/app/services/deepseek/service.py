"""DeepSeekService — drives the DeepSeek web UI with a logged-in session.

This automates https://chat.deepseek.com in a real (headless) browser using
cookies + localStorage exported from Chrome, instead of the paid
platform.deepseek.com API. One browser is launched lazily and reused across
requests; a lock serializes prompts so concurrent callers don't interleave in
the same tab.
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .errors import (
    DeepSeekAuthError,
    DeepSeekResponseError,
    DeepSeekTimeoutError,
)
from .session import DEEPSEEK_ORIGIN, build_storage_state

# See the matching comment in jobright_client.py — load_dotenv() with no path
# resolves relative to the process cwd, not this file, so it silently misses
# backend/.env when launched with a different cwd (e.g. --app-dir backend
# from the project root).
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

# --- Selectors -------------------------------------------------------------
# DeepSeek ships obfuscated, hash-like CSS class names that change between
# frontend releases. These are the stable-ish hooks; if extraction suddenly
# breaks, re-inspect the page and update this block first.
CHAT_INPUT_SELECTOR = "textarea#chat-input, textarea"
ASSISTANT_MESSAGE_SELECTOR = ".ds-markdown, [class*='ds-markdown']"
LOGIN_URL_MARKERS = ("/sign_in", "/login")

# --- Timing ----------------------------------------------------------------
PAGE_LOAD_TIMEOUT_MS = 45_000
REPLY_START_TIMEOUT_S = 60.0
REPLY_TOTAL_TIMEOUT_S = 180.0
STABILITY_POLL_INTERVAL_S = 0.5
# Reply is considered finished once its text stops growing for this long.
STABILITY_QUIET_PERIOD_S = 2.0

_MOCK_SKILLS_RESPONSE = (
    "Skills: Python, FastAPI, React, TypeScript, REST APIs, PostgreSQL\n"
    "Mission: Build and maintain reliable backend services that power the company's core product."
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no")


class DeepSeekService:
    """Extracts structured info from text by prompting DeepSeek's web chat.

    Set one of DEEPSEEK_STORAGE_STATE / DEEPSEEK_COOKIE_FILE / DEEPSEEK_COOKIES
    (see docs/deepseek-session.md). Always uses the real service unless
    DEEPSEEK_MOCK_MODE=true is set explicitly; with no session configured it
    raises rather than returning mock data.
    """

    _prompt_lock: asyncio.Lock | None = None

    def __init__(self, mock_mode: bool | None = None, headless: bool | None = None) -> None:
        if mock_mode is None:
            # Mock is opt-in ONLY. A missing/broken session must surface as a
            # loud auth error rather than silently returning canned skills that
            # look real — see build_storage_state().
            mock_mode = _env_flag("DEEPSEEK_MOCK_MODE", False)

        self.mock_mode = mock_mode
        self.headless = headless if headless is not None else _env_flag("DEEPSEEK_HEADLESS", True)

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def _get_prompt_lock(cls) -> asyncio.Lock:
        if cls._prompt_lock is None:
            cls._prompt_lock = asyncio.Lock()
        return cls._prompt_lock

    @classmethod
    async def shutdown(cls) -> None:
        """Kept for the app lifespan hook.

        Each prompt owns its browser for the duration of the call (see
        _ask_sync), so there is nothing global left to tear down.
        """
        return None

    # -- public API --------------------------------------------------------

    async def extract_skills(self, description: str, prompt: str) -> str:
        """Send `prompt` + `description` to DeepSeek and return the reply text."""
        if self.mock_mode:
            return _MOCK_SKILLS_RESPONSE

        message = f"{prompt}\n\nJob Description:\n{description}"
        return await self.ask(message)

    async def ask(self, message: str) -> str:
        """Run one prompt in a fresh DeepSeek chat and return the reply."""
        if self.mock_mode:
            return _MOCK_SKILLS_RESPONSE

        # Validate the session on the event loop so config errors surface fast.
        storage_state = build_storage_state()

        # Playwright runs on a worker thread using its SYNC api, deliberately.
        # Its async api needs a subprocess-capable loop, but uvicorn selects
        # asyncio.SelectorEventLoop on Windows whenever it runs multiprocess
        # (i.e. with --reload), and Selector loops raise NotImplementedError on
        # subprocess_exec. A worker thread has no running loop at all, so the
        # sync api drives its own driver process and works under any server
        # config, on Windows and Linux alike.
        async with self._get_prompt_lock():
            return await asyncio.to_thread(self._ask_sync, message, storage_state)

    # -- internals (sync; run on a worker thread) --------------------------

    def _ask_sync(self, message: str, storage_state: dict[str, Any]) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=self.headless,
                args=[
                    # Reduce the most obvious headless automation signals.
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            try:
                context = browser.new_context(
                    storage_state=storage_state,
                    viewport={"width": 1280, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                page.goto(DEEPSEEK_ORIGIN, timeout=PAGE_LOAD_TIMEOUT_MS)
                self._assert_logged_in(page)
                self._send_message(page, message)
                return self._read_reply(page)
            finally:
                browser.close()

    @staticmethod
    def _assert_logged_in(page: Any) -> None:
        """Fail fast with a clear message when the session has expired."""
        page.wait_for_timeout(1_500)  # allow client-side auth redirect

        if any(marker in page.url for marker in LOGIN_URL_MARKERS):
            raise DeepSeekAuthError(
                "DeepSeek redirected to the login page — the exported session has "
                "expired. Re-run scripts/capture_deepseek_session.py to refresh it "
                "(see docs/deepseek-session.md)."
            )

        if page.locator(CHAT_INPUT_SELECTOR).count() == 0:
            raise DeepSeekAuthError(
                "DeepSeek chat input not found — the session is likely expired, or "
                "a Cloudflare check is blocking headless access. Re-run "
                "scripts/capture_deepseek_session.py, or set DEEPSEEK_HEADLESS=false "
                "to solve the check in a visible window. See docs/deepseek-session.md."
            )

    @staticmethod
    def _send_message(page: Any, message: str) -> None:
        chat_input = page.locator(CHAT_INPUT_SELECTOR).first
        chat_input.click()
        # fill() goes through the real input pipeline so the React-controlled
        # textarea registers the value and enables the send button.
        chat_input.fill(message)
        page.keyboard.press("Enter")

    @staticmethod
    def _read_reply(page: Any) -> str:
        """Wait for the streamed reply to settle, then return its text.

        DeepSeek streams tokens in, so there's no single 'done' event to await.
        Instead poll the last assistant bubble until its text stops growing.
        """
        started_at = time.monotonic()

        # 1. Wait for an assistant bubble with actual content to appear.
        while not DeepSeekService._reply_text(page):
            if time.monotonic() - started_at > REPLY_START_TIMEOUT_S:
                raise DeepSeekTimeoutError(
                    "DeepSeek accepted the prompt but never started replying "
                    f"within {REPLY_START_TIMEOUT_S:.0f}s."
                )
            time.sleep(STABILITY_POLL_INTERVAL_S)

        # 2. Poll until the text stops changing for the quiet period.
        last_text = ""
        last_change_at = time.monotonic()
        while True:
            current = DeepSeekService._reply_text(page)

            if current != last_text:
                last_text = current
                last_change_at = time.monotonic()
            elif time.monotonic() - last_change_at >= STABILITY_QUIET_PERIOD_S:
                break

            if time.monotonic() - started_at > REPLY_TOTAL_TIMEOUT_S:
                # Return the partial answer rather than losing it outright.
                if last_text:
                    return last_text
                raise DeepSeekTimeoutError(
                    f"DeepSeek reply did not finish within {REPLY_TOTAL_TIMEOUT_S:.0f}s."
                )

            time.sleep(STABILITY_POLL_INTERVAL_S)

        if not last_text:
            raise DeepSeekResponseError("DeepSeek returned an empty reply.")
        return last_text

    @staticmethod
    def _reply_text(page: Any) -> str:
        """Text of the newest assistant message, or '' if there isn't one yet."""
        bubbles = page.locator(ASSISTANT_MESSAGE_SELECTOR)
        if bubbles.count() == 0:
            return ""
        return bubbles.last.inner_text().strip()
