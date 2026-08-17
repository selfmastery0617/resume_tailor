"""A dedicated background event loop for running Playwright on Windows.

Uvicorn's own event loop uses `SelectorEventLoop` (needed for its socket-based
reload/notification plumbing), but Playwright's async API needs
`ProactorEventLoop` to spawn the browser driver as a subprocess — Windows'
asyncio only supports one or the other per loop, never both
(`SelectorEventLoop.subprocess_exec` raises `NotImplementedError`).

This runs one persistent Proactor loop in a background thread and marshals
coroutines onto it via `run_coroutine_threadsafe`, so Playwright work is fully
isolated from whatever loop uvicorn is using. On non-Windows platforms this is
unnecessary but harmless — it just runs a plain background loop.
"""

import asyncio
import sys
import threading
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


class ProactorLoopRunner:
    _loop: asyncio.AbstractEventLoop | None = None
    _thread: threading.Thread | None = None
    _start_lock = threading.Lock()

    @classmethod
    def _get_loop(cls) -> asyncio.AbstractEventLoop:
        with cls._start_lock:
            if cls._loop is not None and cls._loop.is_running():
                return cls._loop

            ready = threading.Event()
            state: dict[str, Any] = {}

            def _run() -> None:
                if sys.platform == "win32":
                    loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined]
                else:
                    loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                state["loop"] = loop
                ready.set()
                try:
                    loop.run_forever()
                finally:
                    loop.close()

            thread = threading.Thread(target=_run, name="deepseek-proactor-loop", daemon=True)
            thread.start()
            ready.wait()

            cls._loop = state["loop"]
            cls._thread = thread
            return cls._loop

    @classmethod
    async def run(cls, coro: Coroutine[Any, Any, T]) -> T:
        """Run `coro` (and everything it awaits) on the dedicated Proactor loop."""
        loop = cls._get_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return await asyncio.wrap_future(future)

    @classmethod
    def shutdown(cls) -> None:
        if cls._loop is not None and cls._loop.is_running():
            cls._loop.call_soon_threadsafe(cls._loop.stop)
        if cls._thread is not None:
            cls._thread.join(timeout=5)
        cls._loop = None
        cls._thread = None
