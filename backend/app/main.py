import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import (
    deepseek,
    experience,
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
app.include_router(templates.router)
app.include_router(profiles.router)
app.include_router(resumes.router)
app.include_router(settings.router)
app.include_router(experience.router)


@app.get("/health")
def health():
    return {"status": "ok"}
