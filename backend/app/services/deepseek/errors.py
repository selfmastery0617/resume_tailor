class DeepSeekError(RuntimeError):
    """Base error for all DeepSeek web-session failures."""


class DeepSeekAuthError(DeepSeekError):
    """Raised when the stored session is missing, malformed, or expired.

    The usual cause is an expired cookie/token — re-export the session from
    Chrome (see docs/deepseek-session.md) to recover.
    """


class DeepSeekTimeoutError(DeepSeekError):
    """Raised when DeepSeek accepted the prompt but never finished replying."""


class DeepSeekResponseError(DeepSeekError):
    """Raised when the page loaded but no assistant reply could be read."""
