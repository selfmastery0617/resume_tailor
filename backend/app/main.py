import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import (
    browser,
    chatgpt,
    deepseek,
    experience,
    jobright,
    jobs,
    profiles,
    resumes,
    settings,
    templates,
)
from app.services.deepseek import DeepSeekService


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Load the sentence-transformers model now, on a worker thread, rather than
    # inside the first extraction. It takes ~30s, and paying it here means one
    # slow startup instead of one request that looks like a hung server.
    asyncio.create_task(asyncio.to_thread(_warm_vector_search))
    yield
    # Close the shared DeepSeek browser so reloads don't leak Chromium processes.
    await DeepSeekService.shutdown()


def _warm_vector_search() -> None:
    from app.services import vector_search

    try:
        vector_search.score_documents("warm up", ["warm up"])
    except Exception as exc:  # noqa: BLE001 - a cold model is not fatal
        logging.getLogger("uvicorn.error").warning("Vector search warm-up failed: %s", exc)


app = FastAPI(title="JobTailor AI API", lifespan=lifespan)

# When this process started, against when the source last changed.
_STARTED_AT = time.time()
_APP_DIR = Path(__file__).resolve().parent
_freshness_cache: dict[str, float] = {"checked_at": 0.0, "newest": 0.0}


def source_freshness() -> dict[str, object]:
    """Whether the code on disk is newer than the code this process loaded.

    Walking the tree costs a few milliseconds, so the answer is cached briefly
    — /health is polled, and the answer only changes when a file is saved.
    """
    now = time.monotonic()
    if now - _freshness_cache["checked_at"] > 5:
        newest = 0.0
        for path in _APP_DIR.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:  # a file being rewritten as we look at it
                continue
        _freshness_cache["newest"] = newest
        _freshness_cache["checked_at"] = now

    newest = _freshness_cache["newest"]
    return {
        "startedAt": _STARTED_AT,
        "newestSourceAt": newest,
        # A second of slack: a save landing during startup is not staleness.
        "stale": newest > _STARTED_AT + 1,
    }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the browser hides Content-Disposition from JS, so the PDF
    # download would silently fall back to a generic filename.
    expose_headers=["Content-Disposition"],
)

app.include_router(jobs.router)
app.include_router(deepseek.router)
app.include_router(jobright.router)
app.include_router(chatgpt.router)
app.include_router(browser.router)
app.include_router(templates.router)
app.include_router(profiles.router)
app.include_router(resumes.router)
app.include_router(settings.router)
app.include_router(experience.router)


@app.get("/health")
def health():
    """Liveness, plus whether this process is running the code on disk.

    A backend started before an edit serves the old code silently: routes 404,
    new settings keys vanish, and the symptom shows up somewhere unrelated —
    which has cost several debugging rounds. Comparing this process's start
    time against the newest source file turns that into something the UI can
    say out loud.
    """
    return {"status": "ok", **source_freshness()}
