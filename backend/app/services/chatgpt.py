"""ChatGPT session detection and prompting.

Unlike DeepSeek — which keeps its bearer in localStorage — ChatGPT
authenticates with an httpOnly session cookie, so "signed in" is detected from
the cookie plus the composer being present rather than from localStorage.

`ask()` mirrors DeepSeekService.ask()/_ask_sync() (deepseek/service.py): one
prompt, one fresh chat, one browser launch per call.

`ask_chained_turns()` is the one exception: the resume-revision pipeline
follows its revision message with a second, in-the-same-chat message asking
ChatGPT to mark the resume's main keywords — that needs everything said so
far still in context, so it can't be a separate, independent ask() call
(which would open a brand-new chat with no memory of what came before). See
experience_service._revise_with_chatgpt().
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Callable, Sequence

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

# Fallback for when Enter doesn't register as "submit" -- observed: the
# composer still holding the full message afterward, nothing sent, and
# nothing to show for it but a silent multi-minute wait for a reply that
# will never come. Not independently verified against a live session (no
# browser access here) -- send_message() only reaches for this after
# confirming Enter alone didn't clear the composer, and raises a clear error
# if this doesn't work either, rather than trusting it blindly.
SEND_BUTTON_SELECTOR = '[data-testid="send-button"], button[aria-label="Send prompt"]'

# Verified the same session: this is the assistant reply container. Bare
# https://chatgpt.com was long assumed to always land on an empty composer,
# never a restored conversation -- true for years against the one original
# shared profile, but observed to NOT hold on a freshly created worker
# profile (see chatgpt_pool.py): its tab landed on an existing conversation
# instead, so a later step's prompt became that chat's first-ever message
# with none of the earlier turns actually present. ensure_new_chat() now
# checks this rather than trusting it, so read_reply()/read_reply_since()
# can still assume "has anything appeared yet" / "changed since baseline"
# is enough -- there is never a genuine previous turn on screen by the time
# they run, because ensure_new_chat() already ruled that out.
ASSISTANT_MESSAGE_SELECTOR = '[data-message-author-role="assistant"]'

# Best-effort corrective click if ensure_new_chat() finds the page not
# actually blank -- keyboard shortcut below is the primary mechanism, this
# is only the fallback, so exact selector drift here is not fatal on its own.
NEW_CHAT_SELECTOR = (
    'a[data-testid="create-new-chat-button"], '
    'button[aria-label="New chat"], a[aria-label="New chat"]'
)

LOGIN_URL_MARKERS = ("/auth/login", "/log-in", "auth.openai.com")

PAGE_LOAD_TIMEOUT_MS = 45_000
# How long to poll for the composer (or a redirect to sign-in) before giving
# up. Empirically, a fresh launch right after a long DeepSeek conversation
# against the same shared profile can take noticeably longer to render than
# a launch in isolation — this must tolerate that, not just a cold start.
LOGIN_CHECK_TIMEOUT_S = 15.0
LOGIN_CHECK_POLL_S = 0.5
# This clock starts only once send_message() has already fully returned
# (ChatGPTConversation._serve() calls them strictly in sequence), so it is
# purely "how long after a confirmed-sent message until anything shows up" --
# not inflated by send_message()'s own, separately-timed-out delivery work.
# Observed a genuine ~120s gap between a message that was confirmed sent and
# its first visible reply text late in a long, heavy conversation with a
# reasoning model (ChatGPT Pro, "high" effort) -- 60s was tuned before that
# combination was in play and is too tight for it.
REPLY_START_TIMEOUT_S = 180.0
# Generous: a reasoning model (ChatGPT Pro, "high" effort) can spend several
# minutes actually thinking before the real answer appears, with no growth in
# the visible text to show it is still working -- see MIN_STABLE_REPLY_CHARS.
REPLY_TOTAL_TIMEOUT_S = 600.0
STABILITY_POLL_INTERVAL_S = 0.5
# Reply is considered finished once its text stops growing for this long.
STABILITY_QUIET_PERIOD_S = 2.0
# A reasoning model's bubble shows a short "Thinking..." placeholder that sits
# unchanged for long stretches while it works -- long enough to look "stable"
# well before real content exists. Below this length, stability alone is not
# enough to call a reply done; only REPLY_TOTAL_TIMEOUT_S expiring will force
# one through, same as any other partial reply.
MIN_STABLE_REPLY_CHARS = 40
# Playwright's own default action timeout (30s) is tuned for a normal-sized
# prompt; a message carrying a large JSON payload (e.g. step 4's -- step 3's
# full candidate list, computed outside the chat and pasted in whole) can
# take longer than that just to type into the contenteditable composer,
# independent of anything about waiting for a reply. This governs
# send_message()'s click()/fill() specifically, not reply waiting.
#
# 90s was observed insufficient in practice, repeatedly: fill()'s own
# actionability check ("visible, enabled and editable" -- stricter than
# click()'s, which had just succeeded moments earlier on the same element)
# kept timing out specifically right after a very large prior reply
# finished rendering (step 5/6's prompts and JSON replies routinely run
# into the tens of thousands of characters) -- consistent with the
# composer staying non-editable for a while after ChatGPT's own client
# finishes settling a big response, longer than 90s allowed for. Same
# story as REPLY_START_TIMEOUT_S's own bump from 60s to 180s.
SEND_ACTION_TIMEOUT_MS = 180_000
# Real keystroke simulation (send_message()'s last-resort fallback) is far
# slower than fill() for a large message -- each character is a genuine
# keydown/input/keyup round trip, not a single DOM write. Generous budget
# since this only runs when fill() has already failed to register.
TYPE_FALLBACK_TIMEOUT_MS = 180_000

__all__ = [
    "PROFILE_DIR",
    "SESSION_PATH",
    "CHATGPT_ORIGIN",
    "SESSION_COOKIE",
    "COMPOSER_SELECTOR",
    "CHAT_INPUT_SELECTOR",
    "ASSISTANT_MESSAGE_SELECTOR",
    "is_signed_in",
    "has_session_cookie",
    "ensure_new_chat",
    "ask",
    "ask_chained_turns",
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
    return has_session_cookie(page) and page.locator(COMPOSER_SELECTOR).count() > 0


def has_session_cookie(page: Any) -> bool:
    """Whether the shared profile holds a live ChatGPT session cookie.

    Matches by prefix, not exact name: NextAuth chunks a session token too
    large for one cookie into SESSION_COOKIE + ".0", ".1", ... and never sets
    the bare name in that case, so an exact match misses a real, signed-in
    session outright.
    """
    cookies = page.context.cookies()
    return any(
        c.get("name", "").startswith(SESSION_COOKIE) and c.get("value") for c in cookies
    )


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


def ensure_new_chat(page: Any) -> bool:
    """Guard against landing on an existing conversation instead of a blank one.

    See ASSISTANT_MESSAGE_SELECTOR's comment above: navigating to
    CHATGPT_ORIGIN was assumed to always produce an empty composer, but that
    was not actually re-checked at runtime, and it was observed to not hold
    on a freshly created worker profile. Steps beyond the first depend on
    everything said earlier in THIS SAME chat still being there -- if the
    page is not genuinely blank, that context is either missing or belongs
    to an unrelated previous conversation, so raise rather than silently
    press on into a chat that would make replies look disconnected and
    generic with no visible error pointing at why.

    Returns True if the page had to be cleared (worth logging -- a caller
    that has somewhere to report it, e.g. the progress log, should say so,
    since this is exactly the condition that produced a real, hard-to-
    diagnose bug once already).
    """
    page.wait_for_timeout(300)
    if bubble_count(page) == 0:
        return False

    # Ctrl+Shift+O is ChatGPT's own documented "start new chat" shortcut --
    # more durable than guessing at a button selector, tried first.
    page.keyboard.press("Control+Shift+O")
    page.wait_for_timeout(500)
    if bubble_count(page) == 0:
        return True

    new_chat_button = page.locator(NEW_CHAT_SELECTOR).first
    if new_chat_button.count() > 0:
        new_chat_button.click(timeout=10_000)
        page.wait_for_timeout(500)

    if bubble_count(page) != 0:
        raise ChatGPTError(
            "Landed on an existing ChatGPT conversation instead of a new, "
            "empty one, and could not clear it. Refusing to continue -- "
            "sending this job's prompts into the wrong chat would silently "
            "produce disconnected, out-of-context replies."
        )
    return True


def _notify_input_changed(chat_input: Any) -> None:
    """Nudge ProseMirror/React to notice fill()'s DOM write.

    fill() writes into the contenteditable DOM directly, bypassing
    ProseMirror's own transaction system entirely -- the visible text
    updates, but ProseMirror's internal editor state (which the send
    button's enabled/disabled state actually reflects) doesn't necessarily
    get told anything changed. A generic 'input' event is the same signal a
    real keystroke would fire, without going through paste handling
    specifically: dispatching a genuine ClipboardEvent('paste') was tried
    here first and confirmed to break something else instead -- above some
    size, ChatGPT's own UI collapses a pasted block into a "Pasted text"
    attachment chip rather than literal inline text, and the model then
    reads that label as part of its own context, producing replies with the
    literal text "Pasted text" embedded inside generated content (observed
    directly inside JSON string fields ChatGPT itself wrote). A plain
    'input' event carries no such paste-specific handling to trigger that.
    """
    chat_input.evaluate("(el) => el.dispatchEvent(new Event('input', { bubbles: true }))")


def _wait_for_send_button_enabled(page: Any, send_button: Any, timeout_s: float = 10.0) -> bool:
    """Poll for the send button to lose its aria-disabled state.

    This is the one signal that actually reflects whether ChatGPT's own app
    registered the composer's content -- not the composer's visible text.
    Observed directly: fill() can leave the composer showing the full
    message while the send button stays aria-disabled="true" for the full
    length of a 90s click timeout, because the DOM write never reached
    ProseMirror's own state (see _notify_input_changed's docstring). A
    truncated composer would also leave the button disabled, so this
    subsumes the old "did the text land" check rather than needing both.
    """
    if send_button.count() == 0:
        return False
    deadline = time.monotonic() + timeout_s
    while True:
        if send_button.get_attribute("aria-disabled") != "true":
            return True
        if time.monotonic() > deadline:
            return False
        page.wait_for_timeout(int(STABILITY_POLL_INTERVAL_S * 1000))


def _wait_for_composer_to_clear(
    page: Any, chat_input: Any, message: str, timeout_s: float = 5.0
) -> bool:
    """Poll up to `timeout_s` for the composer to empty out after a submit
    attempt, rather than a single fixed-delay check right after -- the page
    can still be settling from rendering a large previous reply exactly when
    this runs, and a snap check would misread that brief lag as a genuine
    failure to submit.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        if len(chat_input.inner_text()) <= len(message) * 0.5:
            return True
        if time.monotonic() > deadline:
            return False
        page.wait_for_timeout(int(STABILITY_POLL_INTERVAL_S * 1000))


def send_message(page: Any, message: str) -> None:
    chat_input = page.locator(CHAT_INPUT_SELECTOR).first
    send_button = page.locator(SEND_BUTTON_SELECTOR).first
    chat_input.click(timeout=SEND_ACTION_TIMEOUT_MS)

    # fill() writes directly into the contenteditable ProseMirror editor,
    # same as it would a plain textarea's value -- confirmed working, no
    # keystroke simulation needed for the DOM write itself. Explicit
    # timeout: see SEND_ACTION_TIMEOUT_MS -- a large message can take
    # longer to type than Playwright's 30s default.
    chat_input.fill(message, timeout=SEND_ACTION_TIMEOUT_MS)
    _notify_input_changed(chat_input)

    if not _wait_for_send_button_enabled(page, send_button):
        # Last resort: genuine keystroke simulation. Much slower than
        # fill() for a large message -- each character is a real
        # keydown/input/keyup round trip -- but it is what a real person
        # typing would produce, so it carries neither fill()'s
        # state-desync risk nor a paste event's "collapse into a Pasted
        # text attachment" risk (see _notify_input_changed's docstring).
        chat_input.fill("", timeout=SEND_ACTION_TIMEOUT_MS)
        chat_input.press_sequentially(message, timeout=TYPE_FALLBACK_TIMEOUT_MS)
        if not _wait_for_send_button_enabled(page, send_button, timeout_s=15.0):
            raise ChatGPTError(
                "ChatGPT's send button never became enabled after filling "
                "the composer -- the app's own editor state never "
                "registered the message, so it was never actually "
                "submittable. Not waiting for a reply that was never asked "
                "for."
            )

    # Click the send button directly rather than pressing Enter: Enter's own
    # handler is exposed to the same ProseMirror-state-desync risk that
    # motivated checking the button's enabled state in the first place, and
    # the button is already right here, already confirmed enabled.
    send_button.click(timeout=SEND_ACTION_TIMEOUT_MS)

    # Confirm the click actually submitted rather than trusting it silently
    # -- without this, a failed submit looks identical to a slow reply:
    # nothing raises, and the caller just waits out the full reply timeout
    # for a turn that was never actually asked.
    if not _wait_for_composer_to_clear(page, chat_input, message):
        raise ChatGPTError(
            "Clicked Send but the composer still holds the message -- not "
            "waiting for a reply that was never actually requested."
        )


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
    ask_chained_turns existed), non-zero for a later turn in the same chat. A
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
        elif (
            len(last_text) >= MIN_STABLE_REPLY_CHARS
            and time.monotonic() - last_change_at >= STABILITY_QUIET_PERIOD_S
        ):
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


def read_reply_since(
    page: Any,
    previous: str | None = None,
    is_complete: "Callable[[str], bool] | None" = None,
) -> str:
    """Wait for the streamed reply to settle, then return its text.

    Text-diffing, not bubble-count-based like read_reply() above: ChatGPT's
    message list virtualises in a long-running conversation, unmounting
    older bubbles as new ones arrive, so a raw bubble COUNT captured before
    sending can drift or drop rather than only ever growing (DeepSeek's own
    UI does exactly this -- see DeepSeekService._read_reply's docstring,
    observed going 11 -> 2 mid-chat) -- read_reply()'s `bubble_count(page) >
    after` check then never becomes true, and the call times out waiting
    for a reply that already arrived. Comparing the newest bubble's TEXT
    against what it was right before this turn's message was sent is immune
    to that, since the newest message is always mounted.

    `after`/read_reply() stays as it is for ask_chained_turns(), which only
    ever sends a fixed one-or-two-turn chain -- short enough that
    virtualisation is unlikely to have kicked in. This is for
    ChatGPTConversation, which can run many more sequential turns in one
    chat over the course of a whole extraction (see chatgpt_conversation.py).

    `is_complete`, if given, is an extra gate on top of the stability check:
    even once the text stops growing for STABILITY_QUIET_PERIOD_S, a reply
    is only accepted once is_complete(text) is also true. Plain stability
    alone can't tell "the reply actually finished" from "streaming paused
    for a couple of seconds mid-reply" -- observed directly running two
    ChatGPT sessions concurrently (see chatgpt_pool.py): a large XML reply
    (step 8's whole formatted resume) stopped growing for over 2s mid-
    document, got accepted as done, and the truncated tail (missing its
    closing tags) failed to parse. Pass a callback that checks for whatever
    marks a *genuinely* finished reply (e.g. its closing root tag) for any
    caller expecting a large, structured reply; leave it None (today's
    behavior, unchanged) for callers where that's not easy to check for.
    Only gates the stability-based early return -- the REPLY_TOTAL_TIMEOUT_S
    fallback below still returns whatever partial text exists rather than
    losing it outright, complete-looking or not.
    """
    started_at = time.monotonic()
    baseline = (previous or "").strip()

    # 1. Wait for a reply that is neither empty nor last turn's answer.
    while True:
        current = reply_text(page)
        if current and current != baseline:
            break
        if time.monotonic() - started_at > REPLY_START_TIMEOUT_S:
            raise ChatGPTTimeoutError(
                "ChatGPT accepted the prompt but never started replying "
                f"within {REPLY_START_TIMEOUT_S:.0f}s."
            )
        time.sleep(STABILITY_POLL_INTERVAL_S)

    # 2. Poll until the text stops changing for the quiet period.
    last_text = ""
    last_change_at = time.monotonic()
    while True:
        current = reply_text(page)

        if current != last_text:
            last_text = current
            last_change_at = time.monotonic()
        elif (
            len(last_text) >= MIN_STABLE_REPLY_CHARS
            and last_text != baseline
            and time.monotonic() - last_change_at >= STABILITY_QUIET_PERIOD_S
            and (is_complete is None or is_complete(last_text))
        ):
            break

        if time.monotonic() - started_at > REPLY_TOTAL_TIMEOUT_S:
            # Return the partial answer rather than losing it outright -- but
            # never hand back the previous turn's reply as if it were new.
            if last_text and last_text != baseline:
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
        ensure_new_chat(page)
        send_message(page, message)
        return read_reply(page)


async def ask(message: str, headless: bool | None = None) -> str:
    """Run one prompt in a fresh ChatGPT chat and return the reply.

    Opens a brand-new chat every call — for a caller that needs more messages
    to land in the *same* chat as the first, see ask_chained_turns() below
    instead; a second ask() call would start over with no memory of the
    first.
    """
    if headless is None:
        headless = _env_flag("CHATGPT_HEADLESS", True)

    # See the note in deepseek/service.py's ask(): Playwright's sync api runs
    # on a worker thread on purpose, for the same Windows/--reload reasons.
    async with _get_prompt_lock():
        return await asyncio.to_thread(_ask_sync, message, headless)


def _ask_chained_turns_sync(
    first_message: str,
    build_next_message_fns: Sequence[Callable[[list[str]], "str | None"]],
    headless: bool,
) -> list[str]:
    from app.services.deepseek import browser as browser_mod

    with browser_mod.browser_context(headless=headless) as context:
        page = browser_mod.first_page(context)
        page.goto(
            CHATGPT_ORIGIN, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="domcontentloaded"
        )
        assert_logged_in(page)
        ensure_new_chat(page)
        send_message(page, first_message)
        replies = [read_reply(page)]

        for build_next_message in build_next_message_fns:
            # Each callback decides, from every reply so far, whether its
            # turn is even worth sending (e.g. no point asking ChatGPT to
            # mark keywords in a reply that didn't parse into usable bullets
            # in the first place) -- returning None stops the chain here,
            # short of however many turns were configured.
            next_message = build_next_message(replies)
            if next_message is None:
                break
            before = bubble_count(page)
            send_message(page, next_message)
            replies.append(read_reply(page, after=before))

        return replies


async def ask_chained_turns(
    first_message: str,
    build_next_message_fns: Sequence[Callable[[list[str]], "str | None"]],
    headless: bool | None = None,
) -> list[str]:
    """A run of prompts in the SAME fresh ChatGPT chat, each depending on
    everything said so far.

    Backs the resume pipeline's revision step: revise the bullets/summaries,
    then -- in the same chat, so the later turn still has everything said so
    far in context rather than needing it pasted again -- mark the resume's
    main keywords. Each entry in `build_next_message_fns` receives the list
    of replies received so far (index 0 is the first turn's reply) and
    returns the next message to send, or None to stop the chain there.
    Returns every reply actually received, in order -- always at least one
    (the first turn's), and short of `len(build_next_message_fns) + 1` if a
    callback stopped the chain early.
    """
    if headless is None:
        headless = _env_flag("CHATGPT_HEADLESS", True)

    async with _get_prompt_lock():
        return await asyncio.to_thread(
            _ask_chained_turns_sync, first_message, build_next_message_fns, headless
        )
