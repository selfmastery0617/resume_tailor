"""Background extraction of job descriptions from user-supplied URLs.

One click maps to one fresh DeepSeek conversation. Every eligible selected row
is then sent through that same conversation sequentially, which avoids opening
a browser and creating a chat for every URL. The UI polls the state and may ask
the loop to stop between rows.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.services.progress import progress


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class DescriptionExtractionState:
    state: str = "idle"  # idle | running | done | cancelled | failed
    job_ids: list[str] = field(default_factory=list)
    total: int = 0
    done: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    current_job_id: str | None = None
    current_label: str = ""
    cancel_requested: bool = False
    started_at: str = ""
    finished_at: str = ""
    error: str | None = None
    failures: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "jobIds": list(self.job_ids),
            "total": self.total,
            "done": self.done,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "currentJobId": self.current_job_id,
            "currentLabel": self.current_label,
            "cancelRequested": self.cancel_requested,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "error": self.error,
            "failures": list(self.failures),
        }


class DescriptionExtractionBusy(RuntimeError):
    """A previous Extract JD batch is still running."""


class NoExtractableJobs(ValueError):
    """None of the selected, unlocked rows has a Job URL."""


class JobDescriptionExtractor:
    """Owns the process-wide Extract JD batch, if one is active."""

    def __init__(self) -> None:
        self._state = DescriptionExtractionState()
        self._task: asyncio.Task | None = None
        self._targets: list[dict[str, str]] = []
        self._cancel = False

    @property
    def running(self) -> bool:
        return self._state.state == "running"

    def snapshot(self) -> dict[str, Any]:
        return self._state.snapshot()

    def start(self, job_ids: list[str]) -> dict[str, Any]:
        from app.services import job_store

        if self.running:
            raise DescriptionExtractionBusy("Job descriptions are already being extracted.")

        # list_jobs scopes the lookup to the active profile. Preserve the order
        # supplied by the grid and ignore duplicate ids.
        available = {job["id"]: job for job in job_store.list_jobs()}
        targets: list[dict[str, str]] = []
        seen: set[str] = set()
        for job_id in job_ids:
            job_id = str(job_id)
            if job_id in seen:
                continue
            seen.add(job_id)
            job = available.get(job_id)
            if not job or job.get("locked"):
                continue
            job_url = str(job.get("job_url") or "").strip()
            if not job_url:
                continue
            targets.append(
                {
                    "id": job_id,
                    "url": job_url,
                    "label": str(job.get("title") or job.get("company") or job_id),
                }
            )

        if not targets:
            raise NoExtractableJobs(
                "Select at least one unlocked row with a non-empty Job URL."
            )

        self._cancel = False
        self._targets = targets
        self._state = DescriptionExtractionState(
            state="running",
            job_ids=[target["id"] for target in targets],
            total=len(targets),
            skipped=max(0, len(seen) - len(targets)),
            started_at=_now(),
        )
        self._task = asyncio.create_task(self._run())
        return self.snapshot()

    def cancel(self) -> dict[str, Any]:
        """Stop after the current DeepSeek response has been stored."""
        if self.running:
            self._cancel = True
            self._state.cancel_requested = True
            progress.emit("job-description", "Stopping after the current row…", level="warn")
        return self.snapshot()

    async def _run(self) -> None:
        from app.services import job_store
        from app.services.deepseek import DeepSeekConversation

        state = self._state
        conversation = DeepSeekConversation()
        terminal_state = "failed"
        progress.emit(
            "job-description",
            f"Starting one DeepSeek session for {state.total} job description(s)…",
            level="step",
        )

        try:
            await conversation.start()
            for target in self._targets:
                if self._cancel:
                    break

                state.current_job_id = target["id"]
                state.current_label = target["label"]
                progress.emit(
                    "job-description",
                    f"Extracting {state.done + 1}/{state.total}: {target['label'][:60]}",
                    level="info",
                )
                try:
                    prompt = (
                        f"{target['url']}. That is job url. "
                        "Extract the job description as markdown content"
                    )
                    description = (await conversation.ask(prompt)).strip()
                    if not description:
                        raise ValueError("DeepSeek returned an empty job description.")
                    job_store.update_job(target["id"], {"description": description})
                    state.succeeded += 1
                except Exception as exc:  # noqa: BLE001 - one URL must not end the batch
                    state.failed += 1
                    state.failures.append(f"{target['label']}: {exc}")
                    progress.emit(
                        "job-description",
                        f"Could not extract {target['label']}: {exc}",
                        level="warn",
                    )
                finally:
                    state.done += 1

            terminal_state = "cancelled" if self._cancel else "done"
            progress.emit(
                "job-description",
                f"{'Stopped' if self._cancel else 'Finished'}: "
                f"{state.succeeded}/{state.total} description(s) extracted",
                level="result",
            )
        except Exception as exc:  # startup/auth/browser failure ends the whole batch
            terminal_state = "failed"
            state.error = str(exc)
            progress.emit("job-description", f"Extraction failed: {exc}", level="error")
        finally:
            state.current_job_id = None
            state.current_label = ""
            try:
                await conversation.close()
            except Exception as exc:  # noqa: BLE001 - preserve the useful run result
                progress.emit(
                    "job-description",
                    f"DeepSeek session cleanup failed: {exc}",
                    level="warn",
                )
            state.state = terminal_state
            state.finished_at = _now()


extractor = JobDescriptionExtractor()
