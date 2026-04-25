"""Shared fixtures for API tests — Postgres-backed. Skips when DATABASE_URL not set."""
from __future__ import annotations

import os

# Disable rate limiting and cookie Secure flag before any app imports so the
# module-level checks in api.limiter and api.config pick up these values.
os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")

import pytest
import asyncpg
from httpx import AsyncClient, ASGITransport
from api.auth import create_jwt
from db.postgres import register_jsonb_codec

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USERNAME = "testuser"

TEST_USER_B_ID = "00000000-0000-0000-0000-000000000002"
TEST_USER_B_NAME = "testuser2"


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — API tests skipped")
    return url


async def _ensure_test_user(url: str) -> None:
    c = await asyncpg.connect(dsn=url)
    try:
        await c.execute(
            """
            INSERT INTO users (id, username, email, password_hash, is_admin)
            VALUES ($1::uuid, $2, 'test@example.com', 'x', false)
            ON CONFLICT (id) DO NOTHING
            """,
            TEST_USER_ID, TEST_USERNAME,
        )
    finally:
        await c.close()


async def _ensure_test_user_b(url: str) -> None:
    c = await asyncpg.connect(dsn=url)
    try:
        await c.execute(
            """
            INSERT INTO users (id, username, email, password_hash, is_admin)
            VALUES ($1::uuid, $2, 'testb@example.com', 'x', false)
            ON CONFLICT (id) DO NOTHING
            """,
            TEST_USER_B_ID, TEST_USER_B_NAME,
        )
    finally:
        await c.close()


@pytest.fixture
async def pool():
    """Per-test pool shared by auth_client (routes that access app.state.pool directly)."""
    url = _db_url()
    p = await asyncpg.create_pool(dsn=url, init=register_jsonb_codec)
    yield p
    await p.close()


@pytest.fixture
async def conn():
    """Per-test transactional connection with RLS set. Rolls back after."""
    url = _db_url()
    await _ensure_test_user(url)
    c = await asyncpg.connect(dsn=url)
    await register_jsonb_codec(c)
    tr = c.transaction()
    await tr.start()
    await c.execute("SELECT set_config('app.current_user_id', $1, true)", TEST_USER_ID)
    yield c
    await tr.rollback()
    await c.close()


@pytest.fixture
async def api_client(conn, pool):
    """AsyncClient for non-auth routes. Routes use test conn for DB reads via override,
    but can also access app.state.pool for operations like sync_crontab (typically mocked)."""
    from api.main import create_app
    from db.pool_middleware import get_db_conn

    async def override_get_db_conn():
        yield conn

    app = create_app()
    # ASGITransport does not trigger lifespan — set state directly.
    app.state.pool = pool
    app.dependency_overrides[get_db_conn] = override_get_db_conn

    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client


@pytest.fixture
async def api_client_b(conn, pool):
    """AsyncClient for user B. Shares the same DB connection as api_client so cross-user
    row visibility works within the same transaction."""
    from api.main import create_app
    from db.pool_middleware import get_db_conn

    url = _db_url()
    await _ensure_test_user_b(url)

    async def override_get_db_conn():
        # Switch RLS to user B for the duration of this request
        await conn.execute(
            "SELECT set_config('app.current_user_id', $1, true)", TEST_USER_B_ID
        )
        yield conn
        # Switch back to user A after request completes
        await conn.execute(
            "SELECT set_config('app.current_user_id', $1, true)", TEST_USER_ID
        )

    app = create_app()
    app.state.pool = pool
    app.dependency_overrides[get_db_conn] = override_get_db_conn

    token = create_jwt(TEST_USER_B_ID, TEST_USER_B_NAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client


@pytest.fixture
async def auth_client(pool):
    """AsyncClient for auth routes. Uses real pool (auth routes access app.state.pool directly)."""
    from api.main import create_app

    app = create_app()
    app.state.pool = pool

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
