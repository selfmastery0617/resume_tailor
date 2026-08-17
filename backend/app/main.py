from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import deepseek, jobs
from app.services.deepseek import DeepSeekService


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Close the shared DeepSeek browser so reloads don't leak Chromium processes.
    await DeepSeekService.shutdown()


app = FastAPI(title="JobTailor AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(deepseek.router)


@app.get("/health")
def health():
    return {"status": "ok", "reload_test": True}
