"""Async PostgreSQL connection pool for Tether.

Usage:
    from db.postgres import create_pool, close_pool, get_conn, transaction

    pool = await create_pool()  # once at startup

    async with get_conn(pool, user_id) as conn:
        rows = await conn.fetch("SELECT * FROM tasks WHERE status = $1", "pending")

    async with transaction(pool, user_id) as conn:
        await conn.execute("INSERT INTO tasks ...")  # auto-commits on exit
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar

import asyncpg

logger = logging.getLogger(__name__)


async def register_jsonb_codec(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs so asyncpg auto-serialises dicts/lists.

    asyncpg does NOT do this by default — without codecs, JSONB params must be
    pre-serialised strings, and JSONB reads return TEXT. Call this on every
    connection created outside the pool (tests, one-off scripts).
    """
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )

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
            min_size=0,
            max_size=10,
            max_inactive_connection_lifetime=60,
            command_timeout=30,
            init=register_jsonb_codec,
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

    try:
        async with pool.acquire(timeout=30) as conn:
            async with conn.transaction():
                if user_id is not None:
                    await conn.execute(
                        "SELECT set_config('app.current_user_id', $1, true)", str(user_id)
                    )
                yield conn
    except asyncio.TimeoutError:
        logger.error("get_conn: pool.acquire timed out after 30s — pool exhausted")
        raise


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

    try:
        async with pool.acquire(timeout=30) as conn:
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
    except asyncio.TimeoutError:
        logger.error("transaction: pool.acquire timed out after 30s — pool exhausted")
        raise
