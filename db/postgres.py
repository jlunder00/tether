"""Async PostgreSQL connection pool for Tether.

Usage:
    from db.postgres import create_pool, close_pool, get_conn, transaction

    pool = await create_pool()  # once at startup

    async with get_conn(pool, user_id) as conn:
        rows = await conn.fetch("SELECT * FROM tasks WHERE status = $1", "pending")

    async with transaction(pool, user_id) as conn:
        await conn.execute("INSERT INTO tasks ...")  # auto-commits on exit
"""

import os
from contextlib import asynccontextmanager
from contextvars import ContextVar

import asyncpg

_pool: asyncpg.Pool | None = None

# ContextVar so nested async calls within the same task share one transaction connection.
# Replaces threading.local() from the SQLite layer — asyncio-correct.
_current_conn: ContextVar[asyncpg.Connection | None] = ContextVar(
    "_current_conn", default=None
)


async def create_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"],
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_conn(pool: asyncpg.Pool, user_id: str | None = None):
    """Acquire a connection scoped to a user via RLS.

    Always runs inside a transaction so SET LOCAL user_id persists for
    all queries within the block and resets cleanly when the block exits.
    Re-entrant: if already inside a transaction() block, reuses that connection.
    """
    existing = _current_conn.get()
    if existing is not None:
        yield existing
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            if user_id is not None:
                await conn.execute(
                    "SELECT set_config('app.current_user_id', $1, true)", str(user_id)
                )
            yield conn


@asynccontextmanager
async def transaction(pool: asyncpg.Pool, user_id: str | None = None):
    """Run a block atomically. Re-entrant: nested calls reuse the outer connection.

    Mirrors the SQLite transaction(db_path) context manager API.
    Journal writes, dependent inserts, etc. all commit together or not at all.
    """
    existing = _current_conn.get()
    if existing is not None:
        yield existing
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            if user_id is not None:
                await conn.execute(
                    "SELECT set_config('app.current_user_id', $1, true)", str(user_id)
                )
            token = _current_conn.set(conn)
            try:
                yield conn
            finally:
                _current_conn.reset(token)
