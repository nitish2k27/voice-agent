"""FastAPI app: the router manager. Every router gets plugged in here.

Run from backend/:  uvicorn app.main:app --reload --port 8000   (on Windows: python -m app)
"""
from __future__ import annotations

from contextlib import asynccontextmanager 
## it basicaly makes preload of data before the fastapi is live and clears the data or ask afeter the fastapi goes off basicaly

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import close_async_pool, get_async_conn, open_async_pool
from app.routers import customer, inbound, me
from app.schemas.common import HealthOut

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    #basically we can see here usage of contex manager the open_asyn_pool loads the polling and stpos at yield basically so that whren fatapi run the next funtion will run from there
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
app.include_router(inbound.router)
app.include_router(customer.router)


@app.get("/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    try:
        async with get_async_conn() as conn:
            await conn.execute("select 1")
        return HealthOut(status="ok", db="ok")
    except Exception as e:  # noqa: BLE001
        return HealthOut(status="degraded", db=f"error: {type(e).__name__}")
