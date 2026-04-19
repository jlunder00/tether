"""Shared fixtures for tether_mcp tests — Postgres-backed. Skips without DATABASE_URL."""
from __future__ import annotations

import os
import pytest
import asyncpg

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
ANCHOR_ID = "00000000-0000-0000-0000-000000000010"


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — MCP tests skipped")
    return url


@pytest.fixture(scope="session", autouse=True)
def set_tether_env():
    """Set TETHER_USER_ID so MCP server's _get_user_id() works."""
    os.environ["TETHER_USER_ID"] = TEST_USER_ID
    yield
    os.environ.pop("TETHER_USER_ID", None)


@pytest.fixture
async def pg_pool():
    url = _db_url()
    pool = await asyncpg.create_pool(dsn=url)
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO users (id, username, email, password_hash, is_admin) "
            "VALUES ($1::uuid, 'mcp_testuser', 'mcp_test@example.com', 'x', false) "
            "ON CONFLICT DO NOTHING",
            TEST_USER_ID,
        )
    yield pool
    await pool.close()


@pytest.fixture
async def conn(pg_pool):
    """Per-test transactional connection with RLS. Rolls back after test."""
    c = await pg_pool.acquire()
    tr = c.transaction()
    await tr.start()
    await c.execute("SELECT set_config('app.current_user_id', $1, true)", TEST_USER_ID)
    yield c
    await tr.rollback()
    await pg_pool.release(c)


@pytest.fixture(autouse=True)
async def reset_mcp_pool():
    """Reset the MCP server's cached pool before each test so it re-creates with current DB."""
    import tether_mcp.server as srv
    srv._pool = None
    yield
    if srv._pool is not None:
        await srv._pool.close()
        srv._pool = None
