"""psycopg v3 connection pools to Supabase (session pooler URL).

- Async pool: FastAPI and the LiveKit agent.
- Sync pool: Celery tasks and scripts.
Pools open lazily on first use; FastAPI opens/closes the async pool in its lifespan.
`prepare_threshold=None` keeps us safe if the URL is ever switched to the transaction pooler (6543).
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from psycopg import AsyncConnection, Connection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from app.core.config import settings

# connect_timeout: home networks can take 10+ s to reach Supabase now and then
_CONN_KWARGS = {"prepare_threshold": None, "row_factory": dict_row, "connect_timeout": 20}

_async_pool: AsyncConnectionPool | None = None
_sync_pool: ConnectionPool | None = None


# ---------------------------------------------------------------- async (API, agent)
async def open_async_pool(min_size: int = 1, max_size: int = 5) -> AsyncConnectionPool:
    global _async_pool
    if _async_pool is None:
        _async_pool = AsyncConnectionPool(
            settings.DATABASE_URL, min_size=min_size, max_size=max_size,
            kwargs=_CONN_KWARGS, open=False, name="async-pool",
        )
        await _async_pool.open(wait=True, timeout=30)
    return _async_pool


async def close_async_pool() -> None:
    global _async_pool
    if _async_pool is not None:
        await _async_pool.close()
        _async_pool = None


@asynccontextmanager
async def get_async_conn() -> AsyncIterator[AsyncConnection]:
    pool = await open_async_pool()
    async with pool.connection() as conn:
        yield conn


# ---------------------------------------------------------------- sync (Celery, scripts)
def open_sync_pool(min_size: int = 1, max_size: int = 4) -> ConnectionPool:
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = ConnectionPool(
            settings.DATABASE_URL, min_size=min_size, max_size=max_size,
            kwargs=_CONN_KWARGS, open=False, name="sync-pool",
        )
        _sync_pool.open(wait=True, timeout=30)
    return _sync_pool


def close_sync_pool() -> None:
    global _sync_pool
    if _sync_pool is not None:
        _sync_pool.close()
        _sync_pool = None


@contextmanager
def get_sync_conn() -> Iterator[Connection]:
    with open_sync_pool().connection() as conn:
        yield conn
