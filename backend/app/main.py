"""FastAPI app: the router manager. Every router gets plugged in here.

Run from backend/:  uvicorn app.main:app --reload --port 8000   (on Windows: python -m app)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import close_async_pool, get_async_conn, open_async_pool
from app.routers import me
from app.schemas.common import HealthOut

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_async_pool()
    yield
    await close_async_pool()


app = FastAPI(title="Amrith Sagar Voice Agent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(me.router)


@app.get("/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    try:
        async with get_async_conn() as conn:
            await conn.execute("select 1")
        return HealthOut(status="ok", db="ok")
    except Exception as e:  # noqa: BLE001
        return HealthOut(status="degraded", db=f"error: {type(e).__name__}")
