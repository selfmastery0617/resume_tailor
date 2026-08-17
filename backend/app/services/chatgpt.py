"""ChatGPT web-session sign-in.

Uses the shared BrowserLoginManager. Unlike DeepSeek — which keeps its bearer
in localStorage — ChatGPT authenticates with an httpOnly session cookie, so
"signed in" is detected from the cookie plus the composer being present rather
than from localStorage.
"""

from pathlib import Path
from typing import Any

from app.services.browser_login import BrowserLoginManager, ProviderConfig

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SESSION_PATH = BACKEND_ROOT / "secrets" / "chatgpt_session.json"

CHATGPT_ORIGIN = "https://chatgpt.com"

# Set once authenticated. Name is stable across the auth.openai.com migration.
SESSION_COOKIE = "__Secure-next-auth.session-token"

# The message composer only renders for a signed-in session.
COMPOSER_SELECTOR = "#prompt-textarea, textarea[data-id], form textarea"


def _is_signed_in(page: Any) -> bool:
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


chatgpt_login = BrowserLoginManager(
    ProviderConfig(
        key="chatgpt",
        label="ChatGPT",
        origin=CHATGPT_ORIGIN,
        session_path=SESSION_PATH,
        is_signed_in=_is_signed_in,
        required_cookie=SESSION_COOKIE,
    )
)
