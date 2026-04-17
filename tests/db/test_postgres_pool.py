"""Smoke tests for the async Postgres connection pool and RLS wiring."""

import os
import pytest
import asyncpg

from db.postgres import create_pool, close_pool, get_conn, transaction


@pytest.fixture
def db_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — Postgres not available")
    return url


@pytest.fixture
async def pool(db_url):
    p = await create_pool()
    yield p
    await close_pool()


@pytest.mark.asyncio
async def test_pool_connects(pool):
    async with get_conn(pool) as conn:
        row = await conn.fetchrow("SELECT 1 AS ok")
        assert row["ok"] == 1


@pytest.mark.asyncio
async def test_rls_user_id_propagates(pool):
    test_uuid = "00000000-0000-0000-0000-000000000042"
    async with get_conn(pool, user_id=test_uuid) as conn:
        row = await conn.fetchrow(
            "SELECT current_setting('app.current_user_id', true) AS uid"
        )
        assert row["uid"] == test_uuid


@pytest.mark.asyncio
async def test_unscoped_conn_has_no_user_id(pool):
    async with get_conn(pool) as conn:
        row = await conn.fetchrow(
            "SELECT current_setting('app.current_user_id', true) AS uid"
        )
        assert row["uid"] is None or row["uid"] == ""


@pytest.mark.asyncio
async def test_transaction_commits(pool):
    async with transaction(pool) as conn:
        await conn.execute("SELECT 1")  # no-op, just verify no exception


@pytest.mark.asyncio
async def test_transaction_rollback_on_error(pool):
    """Exception inside transaction() must roll back cleanly."""
    try:
        async with transaction(pool) as conn:
            await conn.execute("SELECT 1")
            raise ValueError("intentional")
    except ValueError:
        pass
    # Pool should still be usable after rollback
    async with get_conn(pool) as conn:
        row = await conn.fetchrow("SELECT 1 AS ok")
        assert row["ok"] == 1


@pytest.mark.asyncio
async def test_reentrant_transaction(pool):
    """Nested get_conn inside transaction() reuses the outer connection."""
    async with transaction(pool, user_id="00000000-0000-0000-0000-000000000001") as outer:
        async with get_conn(pool, user_id="00000000-0000-0000-0000-000000000001") as inner:
            assert outer is inner
