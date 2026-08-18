"""Shared browser for every DeepSeek interaction.

Why a persistent profile instead of capturing a storage-state snapshot:

* A snapshot freezes cookies at one instant. DeepSeek rotates and refreshes
  them, so a snapshot goes stale and the user has to sign in again — the
  recurring expiry problem.
* A persistent profile *is* a browser profile on disk. Cookies, localStorage
  and refresh flows behave exactly as in a normal browser, so a sign-in lasts
  as long as it naturally would.

Note on using the user's own browser: cookies set in their Chrome are not
reachable from this process — they are httpOnly and origin-scoped, which is a
browser security boundary rather than something the code can work around. The
closest equivalents are this dedicated profile (default) or attaching to a Chrome
started with a remote-debugging port (set DEEPSEEK_CDP_URL).

A profile directory can only be opened by one browser at a time, so every use
goes through one lock — a login window and an extraction must not run at once.
"""

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

BACKEND_ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = BACKEND_ROOT / "secrets" / "deepseek-profile"

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
_profile_lock = threading.Lock()


def cdp_url() -> str | None:
    """Attach to an already-running Chrome instead of launching one.

    Start Chrome with --remote-debugging-port=9222 and set
    DEEPSEEK_CDP_URL=http://localhost:9222 to reuse that browser's real
    profile, including any DeepSeek session already signed in there.
    """
    return (os.getenv("DEEPSEEK_CDP_URL") or "").strip() or None


def profile_exists() -> bool:
    """True once a sign-in has populated the profile."""
    return PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir())


def clear_profile() -> None:
    """Forget the stored session (used by an explicit sign-out)."""
    import shutil

    with _profile_lock:
        if PROFILE_DIR.exists():
            shutil.rmtree(PROFILE_DIR, ignore_errors=True)


@contextmanager
def browser_context(headless: bool = True) -> Iterator[Any]:
    """Yield a Playwright context backed by the persistent profile.

    Held for the duration of the caller's work, then closed so the profile lock
    is released and cookie changes are flushed to disk.
    """
    from playwright.sync_api import sync_playwright

    with _profile_lock:
        with sync_playwright() as playwright:
            remote = cdp_url()
            if remote:
                # Reuse the user's own Chrome. Its contexts already carry their
                # real cookies, so nothing needs importing.
                browser = playwright.chromium.connect_over_cdp(remote)
                try:
                    context = (
                        browser.contexts[0]
                        if browser.contexts
                        else browser.new_context(user_agent=USER_AGENT)
                    )
                    yield context
                finally:
                    # Only detach — this browser belongs to the user.
                    browser.close()
                return

            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
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
    """A usable page: reuse the profile's initial tab rather than stacking new ones."""
    for page in context.pages:
        if not page.is_closed():
            return page
    return context.new_page()
