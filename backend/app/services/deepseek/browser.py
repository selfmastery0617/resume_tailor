"""The one shared browser profile — DeepSeek, ChatGPT and Jobright all use it.

Every caller goes through browser_context(). Ordinarily that launches (or
reuses, if the shared sign-in window from shared_browser.py already has it
open) one Playwright-managed persistent profile: cookies, localStorage and
refresh flows behave exactly as in a normal browser, so a sign-in lasts as
long as it naturally would. Origins don't collide — chat.deepseek.com,
chatgpt.com and jobright.ai each keep their own cookies within the one
profile, the same way any ordinary browser holds many sites' logins at once.

Power-user escape hatch: set BROWSER_CDP_URL (or the older DEEPSEEK_CDP_URL) to
attach to a Chrome you started yourself with --remote-debugging-port, reusing
whatever is signed in there instead of this app's own profile. Cookies set in
an ordinary Chrome you did *not* start this way are not reachable from this
process regardless — httpOnly and origin-scoped is a browser security
boundary, not something code can read around.

A profile directory can only be opened by one browser at a time, so every use
of the managed profile goes through one lock — the shared sign-in window and
an extraction must not launch against it at once. The CDP path has no such
constraint: attaching is a lightweight handshake to an already-running
process, not a launch, so it skips the lock entirely.
"""

import os
import threading
import weakref
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Pattern

BACKEND_ROOT = Path(__file__).resolve().parents[3]
# Historically named for DeepSeek, which is why this module lives under
# deepseek/ — but shared by all three providers now.
PROFILE_DIR = BACKEND_ROOT / "secrets" / "shared-profile"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
]

# Chromium refuses to open the same profile twice; serialise all access.
_profile_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()

# Contexts handed out via CDP, so first_page() knows which behaviour applies
# without re-probing reachability. A WeakSet drops the entry on its own once
# the context is closed.
_cdp_contexts: "weakref.WeakSet[Any]" = weakref.WeakSet()


def _lock_for(profile_dir: Path) -> threading.Lock:
    with _locks_guard:
        return _profile_locks.setdefault(Path(profile_dir), threading.Lock())


class ProfileBusy(RuntimeError):
    """Another operation already holds this profile right now."""


@contextmanager
def _held_lock(target: Path, lock_timeout: float | None) -> Iterator[None]:
    """Acquire `target`'s profile lock, then release it on the way out.

    `lock_timeout=None` waits indefinitely — the right choice for background
    work like an extraction, where a short delay is invisible. A finite value
    raises ProfileBusy instead of blocking, for callers a person is looking at.
    """
    lock = _lock_for(target)
    if lock_timeout is None:
        lock.acquire()
    elif not lock.acquire(timeout=lock_timeout):
        raise ProfileBusy(
            f"The browser is in use by another sign-in or task right now. "
            "Try again in a moment."
        )
    try:
        yield
    finally:
        lock.release()


def cdp_url() -> str | None:
    """An explicit remote-debugging endpoint to attach to, if one is set.

    Purely an opt-in power-user escape hatch — there is no auto-detection.
    """
    return (os.getenv("BROWSER_CDP_URL") or os.getenv("DEEPSEEK_CDP_URL") or "").strip() or None


def profile_exists(profile_dir: Path | None = None) -> bool:
    """True once a sign-in has populated the profile."""
    target = Path(profile_dir) if profile_dir is not None else PROFILE_DIR
    return target.exists() and any(target.iterdir())


def clear_profile(profile_dir: Path | None = None, lock_timeout: float | None = None) -> None:
    """Delete the entire profile. Only for tests and scratch directories —
    the shared profile holds every provider's session, so wiping it signs
    everyone out at once. Real sign-out uses clear_origin_cookies() instead.

    Raises ProfileBusy rather than blocking when `lock_timeout` is set and
    something else holds the profile.
    """
    import shutil

    target = Path(profile_dir) if profile_dir is not None else PROFILE_DIR
    with _held_lock(target, lock_timeout):
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def clear_origin_cookies(
    domain: Pattern[str],
    profile_dir: Path | None = None,
    lock_timeout: float | None = None,
) -> None:
    """Forget one origin's cookies, leaving the rest of a shared profile alone.

    This is what sign-out actually does: the profile holds every provider's
    session, so deleting the whole directory would sign the others out too.
    Briefly launches the profile if nothing else already has it open.
    """
    with browser_context(headless=True, profile_dir=profile_dir, lock_timeout=lock_timeout) as context:
        context.clear_cookies(domain=domain)


@contextmanager
def browser_context(
    headless: bool = True,
    profile_dir: Path | None = None,
    lock_timeout: float | None = None,
) -> Iterator[Any]:
    """Yield a Playwright context — an explicitly configured CDP attachment if
    BROWSER_CDP_URL is set, else the shared managed profile.

    Held for the duration of the caller's work, then closed. For the managed
    profile that flushes cookies to disk and releases the lock; for a CDP
    attachment it only detaches the connection, since that browser belongs to
    whatever process started it, not this one.

    `profile_dir` defaults to the shared profile; pass a different one only
    for tests that must not touch it. Has no effect when attached via CDP.

    `lock_timeout` bounds how long the managed profile waits for its lock
    before raising ProfileBusy. Leave it None for background work; pass a few
    seconds for anything a person is watching. A CDP attachment never waits on
    this lock at all — connecting is a lightweight handshake, not a launch.
    """
    from playwright.sync_api import sync_playwright

    remote = cdp_url()
    if remote:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(remote)
            try:
                context = (
                    browser.contexts[0]
                    if browser.contexts
                    else browser.new_context(user_agent=USER_AGENT)
                )
                _cdp_contexts.add(context)
                yield context
            finally:
                # Only detach — this browser belongs to whoever started it.
                browser.close()
        return

    target = Path(profile_dir) if profile_dir is not None else PROFILE_DIR

    with _held_lock(target, lock_timeout):
        with sync_playwright() as playwright:
            target.mkdir(parents=True, exist_ok=True)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(target),
                headless=headless,
                args=LAUNCH_ARGS,
                viewport={"width": 1280, "height": 900},
                user_agent=USER_AGENT,
            )
            try:
                yield context
            finally:
                # Closing the context flushes cookies into the profile.
                context.close()


def first_page(context: Any) -> Any:
    """A usable page.

    In the managed profile, reuse whatever tab is already open — it can only
    be one this app opened itself, since nothing else ever touches that
    profile.

    Attached via CDP, always open a fresh tab instead: reusing an existing one
    could navigate away from whatever is already on screen in that browser.
    """
    if context in _cdp_contexts:
        page = context.new_page()
        try:
            page.bring_to_front()
        except Exception:  # noqa: BLE001 - focusing is a nicety, not required
            pass
        return page

    for page in context.pages:
        if not page.is_closed():
            return page
    return context.new_page()
