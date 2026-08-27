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
# How long to poll for the chat input (or a redirect to sign-in) before
# giving up. A launch against the shared profile can take noticeably longer
# to render right after another provider's browser session just closed
# against the same profile directory than it does in isolation.
LOGIN_CHECK_TIMEOUT_S = 15.0
LOGIN_CHECK_POLL_S = 0.5
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

    @staticmethod
    def mock_reply() -> str:
        """Canned reply used when DEEPSEEK_MOCK_MODE is on."""
        return _MOCK_SKILLS_RESPONSE

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

        # Playwright runs on a worker thread using its SYNC api, deliberately.
        # Its async api needs a subprocess-capable loop, but uvicorn selects
        # asyncio.SelectorEventLoop on Windows whenever it runs multiprocess
        # (i.e. with --reload), and Selector loops raise NotImplementedError on
        # subprocess_exec. A worker thread has no running loop at all, so the
        # sync api drives its own driver process and works under any server
        # config, on Windows and Linux alike.
        async with self._get_prompt_lock():
            return await asyncio.to_thread(self._ask_sync, message)

    # -- internals (sync; run on a worker thread) --------------------------

    def _ask_sync(self, message: str) -> str:
        # Same persistent profile the sign-in wrote to, so cookies refreshed
        # during a prompt are kept rather than discarded with the context.
        from app.services.deepseek import browser as browser_mod

        with browser_mod.browser_context(headless=self.headless) as context:
            page = browser_mod.first_page(context)
            page.goto(DEEPSEEK_ORIGIN, timeout=PAGE_LOAD_TIMEOUT_MS,
                      wait_until="domcontentloaded")
            self._assert_logged_in(page)
            self._send_message(page, message)
            return self._read_reply(page)

    @staticmethod
    def _assert_logged_in(page: Any) -> None:
        """Fail fast with a clear message when the session has expired.

        Polls rather than checking once after a fixed pause: caught this
        misreading "hasn't finished loading yet" as "not signed in" when a
        launch against the shared profile followed closely behind another
        provider's browser session closing (verified while adding the
        ChatGPT revision step, which launches its own browser right after
        this one's DeepSeekConversation closes — see chatgpt.py's
        assert_logged_in for the same fix).
        """
        deadline = time.monotonic() + LOGIN_CHECK_TIMEOUT_S
        while True:
            if any(marker in page.url for marker in LOGIN_URL_MARKERS):
                raise DeepSeekAuthError(
                    "DeepSeek rejected the saved session and redirected to sign-in. "
                    "Open Settings and select Connect DeepSeek to sign in again."
                )
            if page.locator(CHAT_INPUT_SELECTOR).count() > 0:
                return
            if time.monotonic() > deadline:
                raise DeepSeekAuthError(
                    "DeepSeek chat input not found. The session may be invalid, or a "
                    "Cloudflare check may be blocking headless access. Reconnect from "
                    "Settings; if it persists, set DEEPSEEK_HEADLESS=false in backend/.env."
                )
            page.wait_for_timeout(int(LOGIN_CHECK_POLL_S * 1000))

    @staticmethod
    def _send_message(page: Any, message: str) -> None:
        chat_input = page.locator(CHAT_INPUT_SELECTOR).first
        chat_input.click()
        # fill() goes through the real input pipeline so the React-controlled
        # textarea registers the value and enables the send button.
        chat_input.fill(message)
        page.keyboard.press("Enter")

    @staticmethod
    def _read_reply(page: Any, previous: str | None = None) -> str:
        """Wait for the streamed reply to settle, then return its text.

        DeepSeek streams tokens in, so there's no single 'done' event to await.
        Instead poll the last assistant bubble until its text stops growing.

        `previous` is the text of the reply this chat returned last time, and is
        how a new answer is told apart from the one still on screen. Counting
        bubbles cannot do that job: DeepSeek virtualises the message list, so as
        a conversation grows it *unmounts* older messages and the count drops
        (observed going 11 -> 2 mid-chat). Comparing against the previous text
        is immune to that, because the newest message is always mounted.
        """
        started_at = time.monotonic()
        baseline = (previous or "").strip()

        # 1. Wait for a reply that is neither empty nor last turn's answer.
        while True:
            current = DeepSeekService._reply_text(page)
            if current and current != baseline:
                break
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
            elif (
                last_text
                and last_text != baseline
                and time.monotonic() - last_change_at >= STABILITY_QUIET_PERIOD_S
            ):
                break

            if time.monotonic() - started_at > REPLY_TOTAL_TIMEOUT_S:
                # Return the partial answer rather than losing it outright — but
                # never hand back the previous turn's reply as if it were new.
                if last_text and last_text != baseline:
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
        """Text of the newest assistant message, or '' if there isn't one yet.

        ASSISTANT_MESSAGE_SELECTOR is a substring match ([class*='ds-markdown']),
        which can match both the outer container for one reply AND a wrapper
        around each block/paragraph inside it -- a multi-paragraph reply (a
        list of bullets, say) then has several matches per turn, not one.
        Naively taking `.last` on the unfiltered set grabs the LAST INNER
        BLOCK rather than the whole message, silently truncating the reply to
        just its final paragraph (observed directly: a 6-bullet reply read
        back as only its last bullet). Keeping only elements with no matching
        ancestor selects just the outermost message containers, so `.last`
        among THOSE really is the newest message in full, regardless of how
        many blocks it's broken into inside.
        """
        text = page.evaluate(
            """(selector) => {
                const all = Array.from(document.querySelectorAll(selector));
                const topLevel = all.filter(
                    (el) => !all.some((other) => other !== el && other.contains(el))
                );
                const last = topLevel[topLevel.length - 1];
                return last ? last.innerText : "";
            }""",
            ASSISTANT_MESSAGE_SELECTOR,
        )
        return (text or "").strip()
