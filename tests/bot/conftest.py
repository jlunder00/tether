"""Shared Postgres fixtures for bot tests. Skips when DATABASE_URL not set."""
from __future__ import annotations

import os

# Set required config values before any app imports so the config loader
# singleton resolves successfully in test environments (jwt.secret is required).
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-bot-tests")

import pytest
import asyncpg

from db.postgres import register_jsonb_codec

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — bot Postgres tests skipped")
    return url


@pytest.fixture
async def pg_pool():
    url = _db_url()
    pool = await asyncpg.create_pool(dsn=url, init=register_jsonb_codec)
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO users (id, username, email, password_hash, is_admin) "
            "VALUES ($1::uuid, 'testuser', 'test@example.com', 'x', false) ON CONFLICT DO NOTHING",
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
