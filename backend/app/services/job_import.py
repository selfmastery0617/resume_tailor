"""One import at a time, with progress the UI can watch.

An import walks a paginated feed and can take a while, so it runs as a
background task and the browser polls its state. That is the same shape the
progress console already uses, and it survives the page being reloaded
mid-import — the run keeps going and the table catches up.

Rows are stored as they are found rather than in one batch at the end, so a
cancelled or failed run still leaves what it managed to collect.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.schemas.job import JobListing
from app.services.progress import progress

# Guardrails on what the dialog may ask for. A limit of zero would spin the
# feed forever; an enormous one would hammer it.
MIN_LIMIT = 1
MAX_LIMIT = 200


@dataclass
class ImportState:
    """What the client polls. One run's worth."""

    state: str = "idle"  # idle | running | done | cancelled | failed
    roles: list[str] = field(default_factory=list)
    exclude_companies: list[str] = field(default_factory=list)
    limit: int = 10
    # How many feed entries were looked at, versus how many matched. Both are
    # shown: with a narrow role the gap explains why progress is slow.
    scanned: int = 0
    matched: int = 0
    started_at: str = ""
    finished_at: str = ""
    error: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "roles": self.roles,
            "excludeCompanies": self.exclude_companies,
            "limit": self.limit,
            "scanned": self.scanned,
            "matched": self.matched,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "error": self.error,
        }


class ImportBusy(RuntimeError):
    """An import is already running."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class JobImporter:
    """Holds the single in-flight import."""

    def __init__(self) -> None:
        self._state = ImportState()
        self._task: asyncio.Task | None = None
        self._cancel = False

    @property
    def running(self) -> bool:
        return self._state.state == "running"

    def snapshot(self) -> dict[str, Any]:
        return self._state.snapshot()

    def cancel(self) -> dict[str, Any]:
        """Ask the run to stop. It stops between pages, not mid-request."""
        if self.running:
            self._cancel = True
            progress.emit("import", "Cancelling…", level="warn")
        return self.snapshot()

    def start(
        self, roles: list[str], limit: int, exclude_companies: list[str]
    ) -> dict[str, Any]:
        if self.running:
            raise ImportBusy("An import is already running.")

        limit = max(MIN_LIMIT, min(MAX_LIMIT, int(limit)))
        self._cancel = False
        self._state = ImportState(
            state="running",
            roles=[r for r in roles if r.strip()],
            exclude_companies=[c for c in exclude_companies if c.strip()],
            limit=limit,
            started_at=_now(),
        )
        self._task = asyncio.create_task(self._run())
        return self.snapshot()

    async def _run(self) -> None:
        from app.services import job_store
        from app.services.jobright_client import JobrightClient

        state = self._state
        progress.emit(
            "import",
            f"Searching for {', '.join(state.roles) or 'any role'} — up to {state.limit}"
            + (f", excluding {', '.join(state.exclude_companies)}" if state.exclude_companies else ""),
            level="step",
        )

        loop = asyncio.get_running_loop()

        def on_progress(scanned: int, matched: int, listing: JobListing | None) -> None:
            state.scanned = scanned
            state.matched = matched
            if listing is None:
                return
            # Store immediately rather than batching at the end: a run that is
            # cancelled or fails half way should still leave what it found, and
            # the table picks the row up on its next poll.
            try:
                job_store.upsert_many([listing])
            except Exception as exc:  # noqa: BLE001 - one bad row must not end the run
                progress.emit("import", f"Could not store a job: {exc}", level="warn")
            progress.emit(
                "import",
                f"{matched}/{state.limit} — {listing.title[:44]} at {listing.company[:24]}",
                level="info",
            )

        try:
            client = JobrightClient()
            await client.fetch_jobs(
                roles=state.roles,
                limit=state.limit,
                exclude_companies=state.exclude_companies,
                on_progress=on_progress,
                should_cancel=lambda: self._cancel,
            )
            state.state = "cancelled" if self._cancel else "done"
            progress.emit(
                "import",
                f"{'Cancelled' if self._cancel else 'Finished'}: {state.matched} job(s) "
                f"from {state.scanned} scanned",
                level="result",
            )
        except Exception as exc:  # noqa: BLE001 - reported to the dialog
            state.state = "failed"
            state.error = str(exc)
            progress.emit("import", f"Import failed: {exc}", level="error")
        finally:
            state.finished_at = _now()


# One importer for the process, matching the single shared Jobright session.
importer = JobImporter()
