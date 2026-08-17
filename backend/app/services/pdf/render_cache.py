"""Short-lived store for resume render payloads (RG-FR-019, RG-FR-020).

The print route needs the resume data, but putting it in the URL would leak
personal details into logs and history. Instead the payload is held in memory
under a cryptographically random, URL-safe token that:

* expires after five minutes,
* addresses exactly one payload,
* is rejected once expired.

In-memory is deliberate: these payloads are transient by definition, and never
writing them to disk means there is no cache file to leak or clean up.
"""

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

TTL_SECONDS = 300.0  # five minutes


@dataclass
class _Entry:
    payload: dict[str, Any]
    expires_at: float


class RenderCache:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def put(self, payload: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge_expired()
            self._entries[token] = _Entry(payload=payload, expires_at=time.monotonic() + TTL_SECONDS)
        return token

    def get(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                # Expired tokens are removed on access as well as on write, so
                # a stale token can never be redeemed.
                del self._entries[token]
                return None
            return entry.payload

    def discard(self, token: str) -> None:
        with self._lock:
            self._entries.pop(token, None)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        for token in [t for t, e in self._entries.items() if now > e.expires_at]:
            del self._entries[token]


render_cache = RenderCache()
