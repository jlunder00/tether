"""Shared fixtures for Postgres query tests.

Each test gets its own asyncpg.connect() — no shared pool — to avoid event loop
mismatch with pytest-asyncio's function-scoped loop. The connection wraps the
test in a transaction that rolls back on teardown for isolation.
"""
import os
import pytest
import asyncpg

from db.postgres import register_jsonb_codec

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — Postgres tests skipped")
    return url


async def _ensure_test_user(url: str) -> None:
    """Seed deterministic test user outside the rolled-back transaction."""
    c = await asyncpg.connect(dsn=url)
    try:
        await c.execute(
            """
            INSERT INTO users (id, username, email, password_hash, is_admin)
            VALUES ($1::uuid, 'testuser', 'test@example.com', 'x', false)
            ON CONFLICT (id) DO NOTHING
            """,
            TEST_USER_ID,
        )
    finally:
        await c.close()


@pytest.fixture
async def conn():
    """User-scoped connection. Rolls back after each test."""
    url = _db_url()
    await _ensure_test_user(url)
    c = await asyncpg.connect(dsn=url)
    await register_jsonb_codec(c)
    tr = c.transaction()
    await tr.start()
    await c.execute(
        "SELECT set_config('app.current_user_id', $1, true)", TEST_USER_ID
    )
    yield c
    await tr.rollback()
    await c.close()


@pytest.fixture
async def auth_conn():
    """Unscoped connection for auth queries (no RLS). Rolls back after each test."""
    url = _db_url()
    await _ensure_test_user(url)
    c = await asyncpg.connect(dsn=url)
    await register_jsonb_codec(c)
    tr = c.transaction()
    await tr.start()
    yield c
    await tr.rollback()
    await c.close()
