"""In-memory progress log for long-running work.

Extraction takes tens of seconds and makes several non-obvious decisions —
which product won, which two projects were chosen, what the similarity scores
were. Without a trace the UI can only show a spinner, and a surprising result
is impossible to explain.

Events are kept in a capped ring buffer and polled by sequence number, so a
client that reconnects picks up where it left off instead of replaying
everything.
"""

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

MAX_EVENTS = 500

Level = Literal["info", "step", "result", "warn", "error"]


@dataclass
class Event:
    seq: int
    ts: float
    level: Level
    stage: str
    message: str
    # Optional structured payload — e.g. ranked matches with scores.
    data: dict[str, Any] = field(default_factory=dict)


class ProgressLog:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._seq = 0
        self._lock = threading.Lock()

    def emit(
        self,
        stage: str,
        message: str,
        level: Level = "info",
        **data: Any,
    ) -> None:
        with self._lock:
            self._seq += 1
            self._events.append(
                Event(
                    seq=self._seq,
                    ts=time.time(),
                    level=level,
                    stage=stage,
                    message=message,
                    data=data,
                )
            )
            # Ring buffer: a long session must not grow without bound.
            if len(self._events) > MAX_EVENTS:
                del self._events[: len(self._events) - MAX_EVENTS]

    def since(self, seq: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(e) for e in self._events if e.seq > seq]

    def latest_seq(self) -> int:
        with self._lock:
            return self._seq

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            # Sequence is NOT reset: a client polling with an old `since` would
            # otherwise be handed the new events as if it had missed them.


progress = ProgressLog()
