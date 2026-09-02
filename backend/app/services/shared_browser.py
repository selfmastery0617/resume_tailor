"""The one visible browser window each profile's sign-in uses.

Clicking "sign in" for DeepSeek, ChatGPT or Jobright opens a new tab in the
SAME window as any other sign-in for that same profile, rather than a
separate one per provider — and because they share one profile, a session
signed into here is exactly the session extraction reads afterward. There is
only ever one browser per profile to keep straight, and nothing to launch or
attach beforehand: the first sign-in click starts it.

Multiple ChatGPT worker profiles (see chatgpt_pool.py) each get their own
SharedBrowser instance, keyed by profile directory via get_shared_browser()
below -- signing into Worker 2 must open a window against Worker 2's own
profile, not Worker 1's. `shared_browser` (the module-level name every
existing caller already imports) stays the original single instance for the
original shared profile, so nothing outside this file needs to change.

Bounded, not persistent: it closes itself once every tab it opened has been
closed (sign-in finished, or the user just closed the window), so it does not
sit holding its profile's lock indefinitely and blocking extraction that uses
the same profile. A hard cap closes it eventually even if that heuristic is
ever wrong.

Playwright's sync objects are thread-affine, so one dedicated worker thread
owns the browser and everything else talks to it through a queue — the same
pattern DeepSeekConversation uses for a long-lived chat. Work is dispatched as
a plain `context -> result` callable, so callers are not limited to "open a
tab" — Jobright's cookie harvesting reuses the same window this way too.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable

from app.services.deepseek.browser import PROFILE_DIR

# How long with no open tabs and nothing pending before the window closes
# itself. Short: once every sign-in tab is closed there is nothing left to do,
# and holding the profile lock costs extraction real availability.
IDLE_CLOSE_S = 5.0
# Absolute cap regardless of activity, in case a page that never truly "closes"
# (e.g. stuck on an interstitial) defeats the idle check above.
HARD_CAP_S = 30 * 60.0

LAUNCH_LOCK_TIMEOUT_S = 8.0
_POLL_S = 1.0


def _open_or_refocus(origin: str, match: re.Pattern[str]) -> Callable[[Any], None]:
    """A command: open a tab at `origin`, or refocus one already open for it."""

    def run(context: Any) -> None:
        existing = next(
            (p for p in context.pages if not p.is_closed() and match.search(p.url)),
            None,
        )
        page = existing or context.new_page()
        # Always (re)navigate, even for a reused tab: a tab left open from a
        # previous session can be showing stale, cookie-mismatched content --
        # most notably right after sign-out clears cookies out from under it,
        # where the SPA has no way to notice on its own. A fresh load is the
        # only way "Sign in" reliably shows the real, current auth state.
        page.goto(origin, timeout=30_000, wait_until="domcontentloaded")
        page.bring_to_front()

    return run


def _read_cookies(domain: re.Pattern[str]) -> Callable[[Any], list[dict[str, Any]]]:
    """A command: every cookie in the shared context matching `domain`.

    Cookies are context-scoped, not tab-scoped, so this works whether or not a
    tab for that origin happens to still be open.
    """

    def run(context: Any) -> list[dict[str, Any]]:
        return [c for c in context.cookies() if domain.search(c.get("domain") or "")]

    return run


class SharedBrowser:
    """One shared, visible, lazily-launched browser window for one profile."""

    def __init__(self, profile_dir: Path | None = None) -> None:
        # None -> browser_context()'s own default (the original shared
        # profile), same convention as ChatGPTConversation's profile_dir.
        self._profile_dir = profile_dir
        self._commands: "queue.Queue[tuple[Callable[[Any], Any], Future[Any]]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._running = threading.Event()

    def is_open(self) -> bool:
        return self._running.is_set()

    def open_tab(self, origin: str, match: re.Pattern[str], timeout: float = 25.0) -> None:
        """Ensure the shared window is running, then open or refocus a tab.

        `match` identifies an already-open tab for this same provider, so a
        second click brings the existing tab to the front instead of piling up
        duplicates.
        """
        self.run(_open_or_refocus(origin, match), timeout=timeout, start_if_closed=True)

    def cookies_for(self, domain: re.Pattern[str], timeout: float = 10.0) -> list[dict[str, Any]] | None:
        """Cookies matching `domain`, or None if the window isn't open.

        None is not "no cookies" — it means there is nothing live to read, so
        the caller should fall back to whatever it already has stored.
        """
        if not self.is_open():
            return None
        try:
            return self.run(_read_cookies(domain), timeout=timeout, start_if_closed=False)
        except Exception:  # noqa: BLE001 - a person can close the window between
            # is_open() and the command actually running (e.g. clicking the X
            # right after finishing a sign-in), which surfaces here as a raw
            # Playwright TargetClosedError. That is exactly "nothing live to
            # read" too, same as the window never having been open.
            return None

    def check_page(
        self, match: re.Pattern[str], check: Callable[[Any], Any], timeout: float = 10.0
    ) -> Any | None:
        """Run `check(page)` against an already-open tab matching `match`.

        This is what lets a status check see a sign-in the moment it happens,
        even though the shared window's own launch holds the same profile
        lock a fresh probe would otherwise need: rather than compete for it,
        this reads the live page directly, on the thread that already owns it.
        `check` is usually a bool predicate, but can return anything (e.g. a
        diagnostic dict) -- the None below is reserved for "nothing live to
        check", so a predicate's own False must stay distinguishable from it.

        None means either the window is not open, or no tab matches — nothing
        live to check, so the caller should fall back to its own probe.
        """
        if not self.is_open():
            return None

        def run(context: Any) -> Any | None:
            page = next(
                (p for p in context.pages if not p.is_closed() and match.search(p.url)), None
            )
            return None if page is None else check(page)

        try:
            return self.run(run, timeout=timeout, start_if_closed=False)
        except Exception:  # noqa: BLE001 - see the matching note in cookies_for:
            # the window can close between is_open() and the command actually
            # running, which surfaces as a raw Playwright error here. Treat it
            # the same as "nothing live to check".
            return None

    def run(
        self,
        fn: Callable[[Any], Any],
        timeout: float = 25.0,
        start_if_closed: bool = True,
    ) -> Any:
        """Dispatch `fn(context)` onto the worker thread and wait for its result."""
        with self._start_lock:
            if not self._running.is_set():
                if not start_if_closed:
                    return None
                self._launch()

        future: Future[Any] = Future()
        self._commands.put((fn, future))
        return future.result(timeout=timeout)

    # -- lifecycle -----------------------------------------------------------

    def _launch(self) -> None:
        ready: Future[None] = Future()
        self._thread = threading.Thread(
            target=self._run, args=(ready,), name="shared-browser", daemon=True
        )
        self._thread.start()
        ready.result(timeout=30.0)  # re-raises whatever the worker's launch raised
        self._running.set()

    def _run(self, ready: Future[None]) -> None:
        from app.services.deepseek.browser import browser_context

        try:
            with browser_context(
                headless=False,
                profile_dir=self._profile_dir,
                lock_timeout=LAUNCH_LOCK_TIMEOUT_S,
            ) as context:
                if not ready.done():
                    ready.set_result(None)
                self._serve(context)
        except BaseException as exc:  # noqa: BLE001 - reported to the first caller
            if not ready.done():
                ready.set_exception(exc)
        finally:
            self._running.clear()
            self._drain(RuntimeError("The sign-in window closed."))

    def _serve(self, context: Any) -> None:
        deadline = time.monotonic() + HARD_CAP_S
        idle_since: float | None = None

        while True:
            if time.monotonic() > deadline:
                return

            try:
                fn, future = self._commands.get(timeout=_POLL_S)
            except queue.Empty:
                if not context.pages:
                    idle_since = idle_since or time.monotonic()
                    if time.monotonic() - idle_since > IDLE_CLOSE_S:
                        return
                else:
                    idle_since = None
                continue

            idle_since = None
            try:
                future.set_result(fn(context))
            except BaseException as exc:  # noqa: BLE001 - one command, one failure
                future.set_exception(exc)

    def _drain(self, exc: BaseException) -> None:
        while True:
            try:
                _fn, future = self._commands.get_nowait()
            except queue.Empty:
                return
            if not future.done():
                future.set_exception(exc)


_instances: dict[Path, SharedBrowser] = {}
_instances_lock = threading.Lock()


def get_shared_browser(profile_dir: Path) -> SharedBrowser:
    """The one SharedBrowser for `profile_dir`, creating it on first use.

    Each ChatGPT worker profile (see chatgpt_pool.py) needs its own sign-in
    window, since two profiles' persistent contexts are two separate
    Chromium processes that must not be conflated.
    """
    with _instances_lock:
        instance = _instances.get(profile_dir)
        if instance is None:
            instance = SharedBrowser(profile_dir)
            _instances[profile_dir] = instance
        return instance


# The original single instance, keyed the same way get_shared_browser() would
# key it -- every existing caller's `from shared_browser import
# shared_browser` keeps meaning exactly what it always meant.
shared_browser = get_shared_browser(PROFILE_DIR)
