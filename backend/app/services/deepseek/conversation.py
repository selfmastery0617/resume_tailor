"""A single DeepSeek chat, reused for every prompt about one job.

`DeepSeekService.ask()` opens a browser, starts a new chat, sends one prompt and
closes. Extracting one job needs four prompts (skills, two sets of bullets, the
summary), so that meant four browser launches and four unrelated conversations
— slow, and each prompt arrived with no memory of the last.

This keeps one chat open for the whole job. Later prompts land in the same
thread, so the model still has the job description and the bullets it just
wrote when it is asked for the summary.

Threading note: Playwright's sync objects are bound to the thread that created
them, and `asyncio.to_thread` hands successive calls to arbitrary pool threads.
So the browser lives on one dedicated thread and prompts are marshalled to it
over a queue.
"""

import asyncio
import queue
import threading
from concurrent.futures import Future
from typing import Any

from .errors import DeepSeekError
from .service import PAGE_LOAD_TIMEOUT_MS, DeepSeekService
from .session import DEEPSEEK_ORIGIN

# How long to wait for the worker thread to finish closing the browser.
CLOSE_TIMEOUT_S = 30.0

_SHUTDOWN = object()


class DeepSeekConversation:
    """One open chat. Call `start()`, then `ask()` repeatedly, then `close()`."""

    def __init__(self, headless: bool | None = None, mock_mode: bool | None = None) -> None:
        # Reuse the service's env handling rather than re-reading the flags.
        service = DeepSeekService(mock_mode=mock_mode, headless=headless)
        self.mock_mode = service.mock_mode
        self.headless = service.headless

        self._requests: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready: Future = Future()
        self.turns = 0

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Open the browser and land on a fresh chat. Raises if not signed in."""
        if self.mock_mode:
            return
        self._thread = threading.Thread(
            target=self._run, name="deepseek-conversation", daemon=True
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

    async def __aenter__(self) -> "DeepSeekConversation":
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    # -- prompting ---------------------------------------------------------

    async def ask(self, message: str) -> str:
        """Send one more message into the open chat and return the reply."""
        if self.mock_mode:
            self.turns += 1
            return DeepSeekService.mock_reply()

        if self._thread is None or not self._thread.is_alive():
            raise DeepSeekError("The DeepSeek chat session is not running.")

        future: Future = Future()
        self._requests.put((message, future))
        reply = await asyncio.wrap_future(future)
        self.turns += 1
        return reply

    # -- worker thread -----------------------------------------------------

    def _run(self) -> None:
        from app.services.deepseek import browser as browser_mod

        try:
            with browser_mod.browser_context(headless=self.headless) as context:
                page = browser_mod.first_page(context)
                page.goto(
                    DEEPSEEK_ORIGIN,
                    timeout=PAGE_LOAD_TIMEOUT_MS,
                    wait_until="domcontentloaded",
                )
                DeepSeekService._assert_logged_in(page)

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
            self._drain(DeepSeekError("The DeepSeek chat session closed."))

    def _serve(self, page: Any) -> None:
        while True:
            item = self._requests.get()
            if item is _SHUTDOWN:
                return
            message, future = item
            try:
                # In a multi-turn chat the previous reply is still on screen, so
                # "wait for a reply with text" would match the old one and return
                # it instantly. Hand it in so the read can tell them apart.
                previous = DeepSeekService._reply_text(page)
                DeepSeekService._send_message(page, message)
                reply = DeepSeekService._read_reply(page, previous=previous)
                future.set_result(reply)
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
            _message, future = item
            if not future.done():
                future.set_exception(exc)
