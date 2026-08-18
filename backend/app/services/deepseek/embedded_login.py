"""Embedded DeepSeek sign-in — a live view of the backend's own browser.

Why not a real <iframe> pointing at chat.deepseek.com: DeepSeek does allow
framing, but a login completed inside that frame writes cookies into the *user's*
browser under a third-party context. This backend could never read them, so the
status would never flip and extraction would still fail.

Instead the backend drives a headless page in its persistent profile and streams
screenshots to the UI, forwarding clicks and keystrokes back. It looks embedded,
and the session lands exactly where extraction needs it.

Playwright objects are thread-affine, so one worker thread owns the browser and
everything else talks to it through a queue.
"""

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from .browser import browser_context, first_page
from .login import (
    DEFAULT_SESSION_PATH,
    LOGIN_URL_MARKERS,
    REQUIRED_CONFIRMATIONS,
    _is_signed_in,
)
from .session import DEEPSEEK_ORIGIN

# Matches the persistent context's viewport; the UI scales coordinates to it.
VIEWPORT = {"width": 1280, "height": 900}

FRAME_INTERVAL_S = 0.4
SESSION_TIMEOUT_S = 900.0  # 15 minutes of inactivity before giving up

EmbeddedStatus = Literal["idle", "starting", "waiting", "success", "failed", "cancelled"]


@dataclass
class _State:
    status: EmbeddedStatus = "idle"
    detail: str = "Not started."
    url: str = ""
    frame: bytes | None = None
    started_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "sessionId": current_session_id(),
                "status": self.status,
                "detail": self.detail,
                "url": self.url,
                "hasFrame": self.frame is not None,
                "width": VIEWPORT["width"],
                "height": VIEWPORT["height"],
                "elapsedSeconds": int(time.monotonic() - self.started_at) if self.started_at else 0,
            }

    def get_frame(self) -> bytes | None:
        with self._lock:
            return self.frame


_state = _State()
_commands: "queue.Queue[dict[str, Any]]" = queue.Queue()
_thread: threading.Thread | None = None
_stop = threading.Event()

# Every start gets an id. React StrictMode mounts, unmounts and remounts a
# component in development, so the first unmount's stop() would otherwise kill
# the session the remount just created. A stop for a superseded id is ignored.
_session_id = 0
_id_lock = threading.Lock()


def current_session_id() -> int:
    with _id_lock:
        return _session_id


def is_active() -> bool:
    return _state.status in ("starting", "waiting")


def status() -> dict[str, Any]:
    return _state.snapshot()


def frame() -> bytes | None:
    return _state.get_frame()


def send(command: dict[str, Any]) -> None:
    """Queue an input event for the worker thread."""
    if is_active():
        _commands.put(command)


def stop(session_id: int | None = None) -> None:
    """Stop the session identified by `session_id`.

    An id is required: React StrictMode's discarded first mount fires a stop
    before its start has resolved, and an unqualified stop there would tear down
    the session the surviving mount just created.
    """
    if session_id is None or session_id != current_session_id():
        return
    _stop.set()


def start() -> dict[str, Any]:
    """Open the embedded session if one isn't already running."""
    global _thread, _session_id
    if is_active():
        return _state.snapshot()

    with _id_lock:
        _session_id += 1

    _stop.clear()
    while not _commands.empty():  # drop stale input from a previous attempt
        _commands.get_nowait()

    _state.set(
        status="starting",
        detail="Opening DeepSeek…",
        frame=None,
        url="",
        started_at=time.monotonic(),
    )
    _thread = threading.Thread(target=_run, name="deepseek-embedded-login", daemon=True)
    _thread.start()
    return _state.snapshot()


def _apply(page: Any, command: dict[str, Any]) -> None:
    """Apply one forwarded input event to the page."""
    kind = command.get("type")
    if kind == "click":
        page.mouse.click(float(command["x"]), float(command["y"]))
    elif kind == "dblclick":
        page.mouse.dblclick(float(command["x"]), float(command["y"]))
    elif kind == "move":
        page.mouse.move(float(command["x"]), float(command["y"]))
    elif kind == "type":
        # Typed as real key events so React-controlled inputs register it.
        page.keyboard.type(str(command.get("text", "")), delay=12)
    elif kind == "key":
        page.keyboard.press(str(command.get("key", "")))
    elif kind == "scroll":
        page.mouse.wheel(0, float(command.get("dy", 0)))
    elif kind == "navigate":
        page.goto(DEEPSEEK_ORIGIN, timeout=45_000, wait_until="domcontentloaded")


def _run() -> None:
    # A superseded worker must never write into the shared state: its terminal
    # status would otherwise land after a newer session started and clobber it,
    # leaving the UI stuck on "cancelled" while a live session runs.
    my_id = current_session_id()

    def publish(**kwargs: Any) -> bool:
        if my_id != current_session_id():
            return False
        _state.set(**kwargs)
        return True

    def superseded() -> bool:
        return my_id != current_session_id()

    try:
        with browser_context(headless=True) as context:
            page = first_page(context)
            page.set_viewport_size(VIEWPORT)
            page.goto(DEEPSEEK_ORIGIN, timeout=60_000, wait_until="domcontentloaded")
            if not publish(
                status="waiting",
                detail="Sign in to DeepSeek in the panel. It closes itself when you're done.",
            ):
                return  # a newer session owns the state now

            deadline = time.monotonic() + SESSION_TIMEOUT_S
            confirmations = 0

            while not _stop.is_set():
                if superseded():
                    return
                if time.monotonic() > deadline:
                    publish(status="failed", detail="Timed out waiting for sign-in.")
                    return

                # Drain queued input before capturing, so the next frame shows
                # the result of what the user just did.
                while True:
                    try:
                        command = _commands.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        _apply(page, command)
                    except Exception:  # noqa: BLE001 - a bad event must not kill the session
                        pass

                try:
                    shot = page.screenshot(type="jpeg", quality=70)
                    publish(frame=shot, url=page.url)
                except Exception:  # noqa: BLE001 - mid-navigation screenshots fail
                    pass

                confirmations = confirmations + 1 if _is_signed_in(page) else 0
                if confirmations >= REQUIRED_CONFIRMATIONS:
                    page.wait_for_timeout(1_500)  # let cookies settle
                    DEFAULT_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(DEFAULT_SESSION_PATH))
                    try:
                        publish(frame=page.screenshot(type="jpeg", quality=70))
                    except Exception:  # noqa: BLE001
                        pass
                    publish(status="success", detail="Signed in to DeepSeek.", url=page.url)
                    return

                time.sleep(FRAME_INTERVAL_S)

            publish(status="cancelled", detail="Sign-in was cancelled.")
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        publish(status="failed", detail=f"Embedded sign-in failed: {exc}")


__all__ = [
    "start",
    "stop",
    "status",
    "frame",
    "send",
    "is_active",
    "LOGIN_URL_MARKERS",
]
