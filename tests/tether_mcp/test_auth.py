"""Tests for TetherAPIKeyMiddleware — key extraction, validation, rejection."""
from __future__ import annotations

import os
import pytest
from httpx import AsyncClient, ASGITransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from db.pg_queries.api_keys import create_key
from tether_mcp.auth import TetherAPIKeyMiddleware, get_user_id, _user_id_var

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
pytestmark = pytest.mark.asyncio


async def _echo_user(request: Request) -> JSONResponse:
    """Test endpoint that echoes the resolved user_id from contextvar."""
    return JSONResponse({"user_id": get_user_id()})


def _make_test_app(pool_factory):
    inner = Starlette(routes=[Route("/", _echo_user)])
    return TetherAPIKeyMiddleware(inner, pool_factory)


@pytest.fixture
async def pool(pg_pool):
    return pg_pool


@pytest.fixture
async def raw_key(pg_pool):
    """Create a test API key and return the raw key."""
    c = await pg_pool.acquire()
    tr = c.transaction()
    await tr.start()
    await c.execute(
        "INSERT INTO users (id, username, email, password_hash, is_admin) "
        "VALUES ($1::uuid, 'auth_mcp_user', 'auth_mcp@example.com', 'x', false) "
        "ON CONFLICT DO NOTHING",
        TEST_USER_ID,
    )
    key, _ = await create_key(c, TEST_USER_ID, "test-key")
    await tr.commit()
    await pg_pool.release(c)
    yield key


async def test_valid_key_via_header(pool, raw_key):
    app = _make_test_app(lambda: pool)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/", headers={"X-Tether-API-Key": raw_key})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == TEST_USER_ID


async def test_valid_key_via_bearer(pool, raw_key):
    app = _make_test_app(lambda: pool)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == TEST_USER_ID


async def test_valid_key_via_query_param(pool, raw_key):
    app = _make_test_app(lambda: pool)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/?api_key={raw_key}")
    assert resp.status_code == 200
    assert resp.json()["user_id"] == TEST_USER_ID


async def test_missing_key_returns_401(pool):
    # Remove env var so fallback doesn't kick in
    old = os.environ.pop("TETHER_USER_ID", None)
    try:
        app = _make_test_app(lambda: pool)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/")
        assert resp.status_code == 401
    finally:
        if old is not None:
            os.environ["TETHER_USER_ID"] = old


async def test_invalid_key_returns_401(pool):
    app = _make_test_app(lambda: pool)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/", headers={"X-Tether-API-Key": "ttr_notarealkey"})
    assert resp.status_code == 401


async def test_revoked_key_returns_401(pool, raw_key):
    # Revoke the key directly in DB
    c = await pool.acquire()
    await c.execute(
        "UPDATE api_keys SET revoked_at = now() WHERE key_hash = encode(sha256($1::bytea), 'hex')",
        raw_key.encode(),
    )
    await pool.release(c)

    app = _make_test_app(lambda: pool)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/", headers={"X-Tether-API-Key": raw_key})
    assert resp.status_code == 401


async def test_env_fallback_when_no_key(pool):
    """TETHER_USER_ID fallback lets existing single-user deployments keep working."""
    env_uid = "00000000-0000-0000-0000-000000000099"
    os.environ["TETHER_USER_ID"] = env_uid
    try:
        app = _make_test_app(lambda: pool)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == env_uid
    finally:
        os.environ.pop("TETHER_USER_ID", None)
