"""Shared fixtures for Postgres query tests."""
import os
import pytest
import asyncpg

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
async def pg_pool():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — Postgres tests skipped")
    pool = await asyncpg.create_pool(dsn=url, min_size=1, max_size=5)
    # Seed test user — ON CONFLICT DO NOTHING, safe to repeat
    async with pool.acquire() as c:
        await c.execute(
            """
            INSERT INTO users (id, username, email, password_hash, is_admin)
            VALUES ($1::uuid, 'testuser', 'test@example.com', 'x', false)
            ON CONFLICT (id) DO NOTHING
            """,
            TEST_USER_ID,
        )
    yield pool
    await pool.close()


@pytest.fixture
async def conn(pg_pool):
    """Per-test connection with SAVEPOINT isolation — rolls back after each test."""
    c = await pg_pool.acquire()
    await c.execute("SAVEPOINT test_start")
    await c.execute(
        "SELECT set_config('app.current_user_id', $1, true)", TEST_USER_ID
    )
    yield c
    await c.execute("ROLLBACK TO SAVEPOINT test_start")
    await pg_pool.release(c)
