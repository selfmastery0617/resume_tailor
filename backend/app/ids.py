"""UUIDv7 generation (RFC 9562).

Version 7 puts a millisecond timestamp in the high bits, so ids sort by
creation time. That matters for a primary key: random UUIDv4 keys scatter
inserts across the whole B-tree, while time-ordered keys append, which keeps
the index compact and the cache warm.

Postgres gained a builtin ``uuidv7()`` in 18. Generating them here instead
keeps the schema working on 13 through 17, and lets the application know an id
before the row is inserted.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

_MAX_COUNTER = 0xFFF  # 12 bits of rand_a, used as a within-millisecond counter

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """A time-ordered UUID.

    Layout per RFC 9562 §5.7: 48 bits of Unix milliseconds, 4 bits version,
    12 bits (``rand_a``), 2 bits variant, 62 bits of randomness.

    ``rand_a`` holds a counter rather than randomness — the optional monotonic
    method from §6.2. Without it, ids minted inside the same millisecond come
    out in random order, so sorting by id would *nearly* work and quietly fail
    under load. With it, ``sorted(ids)`` is always creation order.
    """
    global _last_ms, _counter

    with _lock:
        ms = int(time.time() * 1000) & 0xFFFF_FFFF_FFFF
        if ms > _last_ms:
            _last_ms, _counter = ms, 0
        else:
            # Same millisecond, or a clock that stepped backwards: keep
            # advancing rather than emitting an id that sorts before its
            # predecessor.
            _counter += 1
            if _counter > _MAX_COUNTER:
                # 4096 ids in one millisecond. Borrow from the next one; the
                # clock catches up on its own.
                _last_ms += 1
                _counter = 0
            ms = _last_ms
        counter = _counter

    value = ms << 80
    value |= 0x7 << 76  # version
    value |= counter << 64
    value |= 0b10 << 62  # variant
    value |= int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)

    return uuid.UUID(int=value)


def uuid7_str() -> str:
    return str(uuid7())
