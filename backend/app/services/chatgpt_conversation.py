"""A single ChatGPT chat, reused for every prompt about one job.

Mirrors DeepSeekConversation (see deepseek/conversation.py) exactly, just
against chatgpt.com instead: chatgpt.ask() opens a brand-new chat every
call, and ask_chained_turns() only runs a short, fixed sequence of turns
decided upfront in one synchronous function -- neither fits a pipeline that
interleaves many .ask() calls across many separate async functions over the
whole job (skills/mission/industry, both companies' bullets and summaries,
the overall summary, the titles, the skill set, and the final whole-resume
assembly). This keeps one chat open for all of it, the same way
DeepSeekConversation does, reusing chatgpt.py's own page-level primitives
(send_message/reply_text/read_reply_since/assert_logged_in) rather than
duplicating the DOM automation itself. Turn differentiation uses
read_reply_since()'s text-diffing, not read_reply()'s bubble counting --
see that function's docstring for why a long chat needs that.

Threading note: same reason as DeepSeekConversation -- Playwright's sync
objects are bound to the thread that created them, and asyncio.to_thread
hands successive calls to arbitrary pool threads. So the browser lives on
one dedicated thread and prompts are marshalled to it over a queue.
"""

import asyncio
import queue
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable

from . import chatgpt as chatgpt_mod
from .chatgpt import CHATGPT_ORIGIN, PAGE_LOAD_TIMEOUT_MS, ChatGPTError

# How long to wait for the worker thread to finish closing the browser.
CLOSE_TIMEOUT_S = 30.0

_SHUTDOWN = object()


class ChatGPTConversation:
    """One open chat. Call `start()`, then `ask()` repeatedly, then `close()`."""

    def __init__(self, headless: bool | None = None, profile_dir: Path | None = None) -> None:
        self.headless = (
            chatgpt_mod._env_flag("CHATGPT_HEADLESS", True) if headless is None else headless
        )
        # None -> browser_context()'s own default (the original shared
        # profile). Passed explicitly by chatgpt_pool-aware callers so
        # concurrent conversations each get their own Chromium profile
        # directory instead of contending for one -- see chatgpt_pool.py.
        self.profile_dir = profile_dir

        self._requests: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready: Future = Future()
        self.turns = 0
        # Set from the worker thread before self._ready resolves, so a
        # caller can log it right after a successful start() -- see
        # chatgpt.ensure_new_chat()'s docstring for why this is worth
        # surfacing rather than silently swallowing.
        self.had_stale_history = False

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Open the browser and land on a fresh chat. Raises if not signed in."""
        self._thread = threading.Thread(
            target=self._run, name="chatgpt-conversation", daemon=True
        )
        self._thread.start()
        # Surfaces an expired session here, once, rather than on the first ask.
        await asyncio.wrap_future(self._ready)

    async def close(self) -> None:
        if self._thread is None:
            return
        self._requests.put(_SHUTDOWN)
        # Joining blocks until the browser has closed and flushed cookies; do it
        # off the event loop.
        await asyncio.to_thread(self._thread.join, CLOSE_TIMEOUT_S)
        self._thread = None

    async def __aenter__(self) -> "ChatGPTConversation":
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    # -- prompting ---------------------------------------------------------

    async def ask(self, message: str, is_complete: "Callable[[str], bool] | None" = None) -> str:
        """Send one more message into the open chat and return the reply.

        `is_complete`, if given, is passed straight through to
        read_reply_since() -- see its docstring for why a plain stability
        check alone isn't always enough for a large, structured reply.
        """
        if self._thread is None or not self._thread.is_alive():
            raise ChatGPTError("The ChatGPT chat session is not running.")

        future: Future = Future()
        self._requests.put((message, is_complete, future))
        reply = await asyncio.wrap_future(future)
        self.turns += 1
        return reply

    # -- worker thread -----------------------------------------------------

    def _run(self) -> None:
        from app.services.deepseek import browser as browser_mod

        try:
            with browser_mod.browser_context(
                headless=self.headless, profile_dir=self.profile_dir
            ) as context:
                page = browser_mod.first_page(context)
                page.goto(
                    CHATGPT_ORIGIN,
                    timeout=PAGE_LOAD_TIMEOUT_MS,
                    wait_until="domcontentloaded",
                )
                chatgpt_mod.assert_logged_in(page)
                self.had_stale_history = chatgpt_mod.ensure_new_chat(page)

                if not self._ready.done():
                    self._ready.set_result(None)
                self._serve(page)
        except BaseException as exc:  # noqa: BLE001 - reported to the caller
            if not self._ready.done():
                self._ready.set_exception(exc)
            else:
                # The browser died mid-conversation; fail the queue rather than
                # leaving `ask()` awaiting a future nothing will ever complete.
                self._drain(exc)
        finally:
            self._drain(ChatGPTError("The ChatGPT chat session closed."))

    def _serve(self, page: Any) -> None:
        # True once a turn has actually gotten a confirmed reply -- from
        # then on, a bubble count of exactly zero means the chat was reset
        # out from under this session (see the check below), not virtualiser
        # drift, which only ever thins older bubbles, never all the way to
        # zero (the newest bubble always stays mounted).
        turn_confirmed = False
        while True:
            item = self._requests.get()
            if item is _SHUTDOWN:
                return
            message, is_complete, future = item
            try:
                if turn_confirmed and chatgpt_mod.bubble_count(page) == 0:
                    # ensure_new_chat() only guards the very first message --
                    # this catches the chat losing its history *later*, e.g.
                    # ChatGPT's own client silently dropping back to a blank
                    # composer during a long reasoning-model wait. Sending
                    # this turn's prompt into that would silently discard
                    # every earlier turn's context instead of failing loud.
                    raise ChatGPTError(
                        "This chat's history just disappeared -- it had at "
                        "least one confirmed reply a moment ago and now "
                        "shows none. Sending the next prompt into what "
                        "looks like a reset chat would silently lose every "
                        "earlier turn's context."
                    )
                # Text of the reply on screen before sending is how this
                # turn's answer gets told apart from the previous one --
                # NOT a bubble count (what ask_chained_turns() uses for its
                # own, much shorter, fixed chain): ChatGPT's message list
                # virtualises in a long-running chat, unmounting older
                # bubbles as new ones arrive, so a count can drift instead
                # of only ever growing. See read_reply_since()'s docstring.
                previous = chatgpt_mod.reply_text(page)
                chatgpt_mod.send_message(page, message)
                reply = chatgpt_mod.read_reply_since(
                    page, previous=previous, is_complete=is_complete
                )
                future.set_result(reply)
                turn_confirmed = True
            except BaseException as exc:  # noqa: BLE001 - one turn, one failure
                # A failed turn should not tear down the chat: the caller can
                # fall back for that step and still use the session for the next.
                future.set_exception(exc)

    def _drain(self, exc: BaseException) -> None:
        """Fail anything still queued so no caller waits forever."""
        while True:
            try:
                item = self._requests.get_nowait()
            except queue.Empty:
                return
            if item is _SHUTDOWN:
                continue
            _message, _is_complete, future = item
            if not future.done():
                future.set_exception(exc)
