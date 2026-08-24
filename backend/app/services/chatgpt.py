"""ChatGPT session detection and prompting.

Unlike DeepSeek — which keeps its bearer in localStorage — ChatGPT
authenticates with an httpOnly session cookie, so "signed in" is detected from
the cookie plus the composer being present rather than from localStorage.

`ask()` mirrors DeepSeekService.ask()/_ask_sync() (deepseek/service.py): one
prompt, one fresh chat, one browser launch per call.

`ask_two_turns()` is the one exception: the resume-revision pipeline now
follows its revision message with a second, in-the-same-chat message asking
ChatGPT to mark the resume's main keywords — that needs the revised text
still in context, so it cannot be a second, independent ask() call (which
would open a brand-new chat with no memory of the first). See
experience_service._revise_with_chatgpt().
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Callable

from app.services.deepseek.browser import PROFILE_DIR

BACKEND_ROOT = Path(__file__).resolve().parents[2]
# Superseded by the shared profile itself; kept only so an old snapshot from
# before that migration can still be adopted. See chatgpt_session.py.
SESSION_PATH = BACKEND_ROOT / "secrets" / "chatgpt_session.json"

CHATGPT_ORIGIN = "https://chatgpt.com"

# Set once authenticated. Name is stable across the auth.openai.com migration.
SESSION_COOKIE = "__Secure-next-auth.session-token"

# The message composer only renders for a signed-in session. Existence-check
# only (is_signed_in just does .count() > 0) — matches either the real
# composer or its hidden fallback textarea, which is fine for a boolean.
COMPOSER_SELECTOR = "#prompt-textarea, textarea[data-id], form textarea"

# For actually typing into the composer, COMPOSER_SELECTOR is not enough: it
# matches TWO elements in DOM order, and .first lands on a hidden fallback
# <textarea> that something else intercepts clicks on. Verified against a
# live signed-in session (2026-08-20): the real input is a contenteditable
# ProseMirror <div id="prompt-textarea">, which .fill() works on directly.
CHAT_INPUT_SELECTOR = '#prompt-textarea[contenteditable="true"]'

# Verified the same session: this is the assistant reply container, and each
# ask() call opens a brand-new chat (bare https://chatgpt.com always lands on
# an empty composer, never a restored conversation), so unlike DeepSeek there
# is never a previous turn's reply still on screen to tell apart from a new
# one — read_reply() only needs "has anything appeared yet".
ASSISTANT_MESSAGE_SELECTOR = '[data-message-author-role="assistant"]'

LOGIN_URL_MARKERS = ("/auth/login", "/log-in", "auth.openai.com")

PAGE_LOAD_TIMEOUT_MS = 45_000
# How long to poll for the composer (or a redirect to sign-in) before giving
# up. Empirically, a fresh launch right after a long DeepSeek conversation
# against the same shared profile can take noticeably longer to render than
# a launch in isolation — this must tolerate that, not just a cold start.
LOGIN_CHECK_TIMEOUT_S = 15.0
LOGIN_CHECK_POLL_S = 0.5
REPLY_START_TIMEOUT_S = 60.0
REPLY_TOTAL_TIMEOUT_S = 180.0
STABILITY_POLL_INTERVAL_S = 0.5
# Reply is considered finished once its text stops growing for this long.
STABILITY_QUIET_PERIOD_S = 2.0

__all__ = [
    "PROFILE_DIR",
    "SESSION_PATH",
    "CHATGPT_ORIGIN",
    "SESSION_COOKIE",
    "COMPOSER_SELECTOR",
    "CHAT_INPUT_SELECTOR",
    "ASSISTANT_MESSAGE_SELECTOR",
    "is_signed_in",
    "ask",
    "ask_two_turns",
    "ChatGPTError",
    "ChatGPTAuthError",
    "ChatGPTResponseError",
    "ChatGPTTimeoutError",
]


class ChatGPTError(RuntimeError):
    """Base for ChatGPT automation failures."""


class ChatGPTAuthError(ChatGPTError):
    """The session is missing, expired, or blocked."""


class ChatGPTResponseError(ChatGPTError):
    """A reply was empty or otherwise unusable."""


class ChatGPTTimeoutError(ChatGPTError):
    """ChatGPT never started, or never finished, replying in time."""


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no")


def is_signed_in(page: Any) -> bool:
    """True when the session cookie exists and the composer has rendered.

    Requiring both avoids saving a half-finished session: the cookie can appear
    during a multi-step login before the account is actually usable.
    """
    cookies = page.context.cookies()
    has_cookie = any(
        c.get("name") == SESSION_COOKIE and c.get("value") for c in cookies
    )
    if not has_cookie:
        return False
    return page.locator(COMPOSER_SELECTOR).count() > 0


# -- single-shot prompting --------------------------------------------------


def assert_logged_in(page: Any) -> None:
    """Fail fast with a clear message when the session has expired.

    Polls rather than checking once after a fixed pause: verified in testing
    that ChatGPT's composer can take longer than a single short pause to
    render — reliably fast in isolation, but slower immediately after a long
    DeepSeek conversation just closed against the same shared browser
    profile. A single early check would misread "hasn't finished loading
    yet" as "not signed in".
    """
    deadline = time.monotonic() + LOGIN_CHECK_TIMEOUT_S
    while True:
        if any(marker in page.url for marker in LOGIN_URL_MARKERS):
            raise ChatGPTAuthError(
                "ChatGPT rejected the saved session and redirected to sign-in. "
                "Open Settings and reconnect ChatGPT."
            )
        if page.locator(CHAT_INPUT_SELECTOR).count() > 0:
            return
        if time.monotonic() > deadline:
            raise ChatGPTAuthError(
                "ChatGPT chat input not found. The session may be invalid, or a "
                "Cloudflare check may be blocking headless access. Reconnect from "
                "Settings; if it persists, set CHATGPT_HEADLESS=false in backend/.env."
            )
        page.wait_for_timeout(int(LOGIN_CHECK_POLL_S * 1000))


def send_message(page: Any, message: str) -> None:
    chat_input = page.locator(CHAT_INPUT_SELECTOR).first
    chat_input.click()
    # fill() writes directly into the contenteditable ProseMirror editor, same
    # as it would a plain textarea's value — confirmed working, no keystroke
    # simulation needed.
    chat_input.fill(message)
    page.keyboard.press("Enter")


def reply_text(page: Any) -> str:
    """Text of the newest assistant message, or '' if there isn't one yet."""
    bubbles = page.locator(ASSISTANT_MESSAGE_SELECTOR)
    if bubbles.count() == 0:
        return ""
    return bubbles.last.inner_text().strip()


def bubble_count(page: Any) -> int:
    return page.locator(ASSISTANT_MESSAGE_SELECTOR).count()


def read_reply(page: Any, after: int = 0) -> str:
    """Wait for the streamed reply to settle, then return its text.

    ChatGPT streams tokens in, so there is no single 'done' event to await.
    Poll the last assistant bubble until its text stops growing.

    `after` is how many assistant bubbles were already on screen before this
    turn's message was sent — 0 for a single-shot chat (every call before
    ask_two_turns existed), non-zero for a later turn in the same chat. A
    previous turn's bubble is already finished and its text is already
    stable, so without this, step 1 below ("wait for a reply to appear") can
    read that old, unchanged bubble as if it just arrived, and step 2 can
    then find it "stable" a moment later — returning the *previous* turn's
    answer for this one. Waiting for the bubble *count* to grow past `after`
    is what actually distinguishes them; text alone cannot.
    """
    started_at = time.monotonic()

    # 1. Wait for a genuinely new reply to appear (bubble count grown past
    # `after`) and start actually streaming text in (non-empty) -- a fresh
    # bubble typically renders empty for a moment before tokens arrive, and
    # without this second condition that instant would look "stable" the
    # moment step 2 sees the same empty string twice in a row.
    while True:
        current = reply_text(page) if bubble_count(page) > after else ""
        if current:
            break
        if time.monotonic() - started_at > REPLY_START_TIMEOUT_S:
            raise ChatGPTTimeoutError(
                "ChatGPT accepted the prompt but never started replying "
                f"within {REPLY_START_TIMEOUT_S:.0f}s."
            )
        time.sleep(STABILITY_POLL_INTERVAL_S)

    # 2. Poll until the text stops changing for the quiet period.
    last_text = current
    last_change_at = time.monotonic()
    while True:
        current = reply_text(page)

        if current != last_text:
            last_text = current
            last_change_at = time.monotonic()
        elif time.monotonic() - last_change_at >= STABILITY_QUIET_PERIOD_S:
            break

        if time.monotonic() - started_at > REPLY_TOTAL_TIMEOUT_S:
            # Return the partial answer rather than losing it outright.
            if last_text:
                return last_text
            raise ChatGPTTimeoutError(
                f"ChatGPT reply did not finish within {REPLY_TOTAL_TIMEOUT_S:.0f}s."
            )

        time.sleep(STABILITY_POLL_INTERVAL_S)

    if not last_text:
        raise ChatGPTResponseError("ChatGPT returned an empty reply.")
    return last_text


_prompt_lock: "asyncio.Lock | None" = None


def _get_prompt_lock() -> asyncio.Lock:
    global _prompt_lock
    if _prompt_lock is None:
        _prompt_lock = asyncio.Lock()
    return _prompt_lock


def _ask_sync(message: str, headless: bool) -> str:
    from app.services.deepseek import browser as browser_mod

    with browser_mod.browser_context(headless=headless) as context:
        page = browser_mod.first_page(context)
        page.goto(
            CHATGPT_ORIGIN, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="domcontentloaded"
        )
        assert_logged_in(page)
        send_message(page, message)
        return read_reply(page)


async def ask(message: str, headless: bool | None = None) -> str:
    """Run one prompt in a fresh ChatGPT chat and return the reply.

    Opens a brand-new chat every call — for a caller that needs a second
    message to land in the *same* chat as the first, see ask_two_turns()
    below instead; a second ask() call would start over with no memory of
    the first.
    """
    if headless is None:
        headless = _env_flag("CHATGPT_HEADLESS", True)

    # See the note in deepseek/service.py's ask(): Playwright's sync api runs
    # on a worker thread on purpose, for the same Windows/--reload reasons.
    async with _get_prompt_lock():
        return await asyncio.to_thread(_ask_sync, message, headless)


def _ask_two_turns_sync(
    first_message: str,
    build_second_message: Callable[[str], "str | None"],
    headless: bool,
) -> tuple[str, "str | None"]:
    from app.services.deepseek import browser as browser_mod

    with browser_mod.browser_context(headless=headless) as context:
        page = browser_mod.first_page(context)
        page.goto(
            CHATGPT_ORIGIN, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="domcontentloaded"
        )
        assert_logged_in(page)
        send_message(page, first_message)
        first_reply = read_reply(page)

        # The caller decides, from the first reply's actual content, whether
        # a follow-up is even worth sending (e.g. no point asking ChatGPT to
        # mark keywords in a reply that didn't parse into usable bullets in
        # the first place) -- returning None here skips the second turn.
        second_message = build_second_message(first_reply)
        if second_message is None:
            return first_reply, None

        before = bubble_count(page)
        send_message(page, second_message)
        second_reply = read_reply(page, after=before)
        return first_reply, second_reply


async def ask_two_turns(
    first_message: str,
    build_second_message: Callable[[str], "str | None"],
    headless: bool | None = None,
) -> tuple[str, "str | None"]:
    """Two prompts in the SAME fresh ChatGPT chat, back to back.

    Backs the resume pipeline's revision step: the first turn asks ChatGPT to
    revise the bullets/summaries, and the second -- in the same chat, so it
    still has that revised text in context rather than needing it pasted
    again -- asks it to mark the resume's main keywords. `build_second_message`
    receives the first turn's raw reply and returns the message to send next,
    or None to skip the second turn entirely.
    """
    if headless is None:
        headless = _env_flag("CHATGPT_HEADLESS", True)

    async with _get_prompt_lock():
        return await asyncio.to_thread(
            _ask_two_turns_sync, first_message, build_second_message, headless
        )
