"""A small pool of independent ChatGPT browser profiles for concurrent use.

Bulk extraction used to serialize every job through one shared browser
profile (one Chromium `user_data_dir` can only be opened by one process at a
time -- see deepseek/browser.py's `_held_lock`/`_profile_locks`, which is
already keyed *per profile path*). This module is what actually uses that:
N separate profile directories, each independently signed into the same
ChatGPT account, so N jobs' pipelines can run as N genuinely concurrent
Chromium processes instead of queueing behind one lock.

Worker 1 is always the existing, already-signed-in shared profile
(chatgpt.PROFILE_DIR) -- nothing changes for someone using just one worker.
Worker 2+ are sibling directories that each need their own one-time manual
sign-in (see the "ChatGPT Workers" section on Settings); there is no attempt
to clone a signed-in profile's cookies into a new one, since NextAuth session
tokens can rotate on use and a cloned copy could silently stop working.

How many workers exist and how many run at once are the same number
(chatGptWorkerCount) -- a decoupled "N profiles, M concurrent" version of
this was tried and reverted: it added a second setting that immediately
caused its own confusion (defaulted differently than expected, out of sync
with what was actually live). One number, straightforwardly enforced by the
queue below, is easier to reason about and to keep correct.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from app.services.deepseek.browser import PROFILE_DIR

MIN_WORKERS = 1
MAX_WORKERS = 4
DEFAULT_WORKER_COUNT = 2


@dataclass(frozen=True)
class ChatGptWorker:
    """One pool slot: a 1-based index (matches the "Worker N" UI label) and
    the profile directory it owns."""

    index: int
    profile_dir: Path


def worker_profile_dir(index: int) -> Path:
    """Worker 1 is the original shared profile everyone already uses; every
    worker above that gets its own sibling directory, never created or
    touched until that worker is actually configured/signed into."""
    if index == 1:
        return PROFILE_DIR
    return PROFILE_DIR.parent / f"chatgpt-worker-{index}"


def workers() -> list[ChatGptWorker]:
    """Every configured worker, built fresh from the current
    chatGptWorkerCount setting -- cheap, so there's no need to cache it
    across a setting change."""
    from app.services import settings_service

    try:
        count = int(settings_service.get_settings().get("chatGptWorkerCount") or DEFAULT_WORKER_COUNT)
    except (TypeError, ValueError):
        count = DEFAULT_WORKER_COUNT
    count = max(MIN_WORKERS, min(MAX_WORKERS, count))
    return [ChatGptWorker(index=i, profile_dir=worker_profile_dir(i)) for i in range(1, count + 1)]


def get_worker(index: int) -> ChatGptWorker:
    """A single worker by index, regardless of whether it's currently
    within the configured count -- signing into "Worker 3" while
    chatGptWorkerCount is still 2 should work (it just won't be handed out
    by acquire_worker() until the count is raised to include it)."""
    return ChatGptWorker(index=index, profile_dir=worker_profile_dir(index))


class _WorkerPool:
    """Semaphore-via-queue: pre-seed with every configured worker, get() to
    acquire, put_nowait() to release. Gives FIFO fairness and a hard
    concurrency cap for free, and re-seeding on a count change is just
    rebuilding the queue -- no separate Semaphore + tracking to keep in
    sync with it.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ChatGptWorker] | None = None
        self._seeded_indexes: tuple[int, ...] = ()
        self._lock = asyncio.Lock()

    async def _queue_for_current_config(self) -> "asyncio.Queue[ChatGptWorker]":
        current = workers()
        current_indexes = tuple(w.index for w in current)
        async with self._lock:
            if self._queue is None or self._seeded_indexes != current_indexes:
                # A resize mid-flight: any worker already checked out keeps
                # running (it isn't in the old queue to lose), the new queue
                # just reflects the new full set once everything currently
                # borrowed is returned to whichever queue's put() its holder
                # still references. Simplest safe behavior for a setting
                # that changes rarely, not a live-traffic hot path.
                queue: "asyncio.Queue[ChatGptWorker]" = asyncio.Queue()
                for worker in current:
                    queue.put_nowait(worker)
                self._queue = queue
                self._seeded_indexes = current_indexes
            return self._queue

    async def acquire(self) -> tuple[ChatGptWorker, "asyncio.Queue[ChatGptWorker]"]:
        """Returns the worker plus the queue it was drawn from, so a release
        always goes back to that same queue -- even if a resize happened
        while this worker was checked out and _queue now points elsewhere."""
        queue = await self._queue_for_current_config()
        worker = await queue.get()
        return worker, queue

    def release(self, worker: ChatGptWorker, queue: "asyncio.Queue[ChatGptWorker]") -> None:
        queue.put_nowait(worker)


_pool = _WorkerPool()


async def acquire_worker() -> ChatGptWorker:
    """Blocks until a worker is free. Prefer borrow_worker() below, which
    guarantees release even if the caller raises."""
    worker, _queue = await _pool.acquire()
    return worker


@asynccontextmanager
async def borrow_worker() -> AsyncIterator[ChatGptWorker]:
    """Acquire a worker for the duration of the block, always releasing it
    back to the pool it came from -- even if a resize happened while it was
    checked out."""
    worker, queue = await _pool.acquire()
    try:
        yield worker
    finally:
        _pool.release(worker, queue)
