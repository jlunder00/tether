"""Tests for TetherAPIKeyMiddleware — key extraction, validation, rejection."""
from __future__ import annotations

import asyncio
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
TEST_USER_ID_B = "00000000-0000-0000-0000-000000000002"
pytestmark = pytest.mark.asyncio


async def _echo_user(request: Request) -> JSONResponse:
    """Test endpoint that echoes the resolved user_id from contextvar."""
    return JSONResponse({"user_id": get_user_id()})


def _make_test_app(pool_factory):
    inner = Starlette(routes=[Route("/", _echo_user)])
    return TetherAPIKeyMiddleware(inner, pool_factory)


async def _make_key(pool, user_id: str, name: str, username: str, email: str) -> str:
    """Helper: ensure user exists and create a key, returning the raw key."""
    c = await pool.acquire()
    tr = c.transaction()
    await tr.start()
    await c.execute(
        "INSERT INTO users (id, username, email, password_hash, is_admin) "
        "VALUES ($1::uuid, $2, $3, 'x', false) ON CONFLICT DO NOTHING",
        user_id, username, email,
    )
    key, _ = await create_key(c, user_id, name)
    await tr.commit()
    await pool.release(c)
    return key


@pytest.fixture
async def pool(pg_pool):
    return pg_pool


@pytest.fixture
async def raw_key(pg_pool):
    """Create a test API key for TEST_USER_ID and return the raw key."""
    return await _make_key(
        pg_pool, TEST_USER_ID, "test-key", "auth_mcp_user", "auth_mcp@example.com"
    )


@pytest.fixture
async def raw_key_b(pg_pool):
    """Create a test API key for TEST_USER_ID_B and return the raw key."""
    return await _make_key(
        pg_pool, TEST_USER_ID_B, "test-key-b", "auth_mcp_user_b", "auth_mcp_b@example.com"
    )


# ── Happy path ───────────────────────────────────────────────────────────────

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


# ── Rejection cases ──────────────────────────────────────────────────────────

async def test_missing_key_returns_401(pool):
    app = _make_test_app(lambda: pool)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/")
    assert resp.status_code == 401


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


async def test_query_param_returns_401(pool, raw_key):
    """Keys in query params are not supported — they appear in access logs."""
    app = _make_test_app(lambda: pool)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/?api_key={raw_key}")
    assert resp.status_code == 401


# ── Env-var fallback does NOT apply to HTTP transport ───────────────────────

async def test_env_var_does_not_bypass_http_auth(pool):
    """TETHER_USER_ID env var must not grant access over HTTP — that's the stdio fallback."""
    original = os.environ.get("TETHER_USER_ID")
    os.environ["TETHER_USER_ID"] = "00000000-0000-0000-0000-000000000099"
    try:
        app = _make_test_app(lambda: pool)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/")
        assert resp.status_code == 401
    finally:
        if original is None:
            os.environ.pop("TETHER_USER_ID", None)
        else:
            os.environ["TETHER_USER_ID"] = original


async def test_env_var_set_with_invalid_key_still_returns_401(pool):
    """Env var must not rescue a bad key — key validation must always run when a key is present."""
    original = os.environ.get("TETHER_USER_ID")
    os.environ["TETHER_USER_ID"] = "00000000-0000-0000-0000-000000000099"
    try:
        app = _make_test_app(lambda: pool)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/", headers={"X-Tether-API-Key": "ttr_notarealkey"})
        assert resp.status_code == 401
    finally:
        if original is None:
            os.environ.pop("TETHER_USER_ID", None)
        else:
            os.environ["TETHER_USER_ID"] = original


# ── Duplicate header handling ────────────────────────────────────────────────

async def test_first_header_value_wins_on_duplicates(pool, raw_key):
    """First X-Tether-API-Key header wins; second (garbage) is ignored."""
    app = _make_test_app(lambda: pool)
    # httpx deduplicates headers — test via raw ASGI scope instead
    from starlette.testclient import TestClient
    import threading

    result = {}

    async def _run():
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [
                (b"x-tether-api-key", raw_key.encode()),
                (b"x-tether-api-key", b"ttr_garbage"),
            ],
        }
        responses = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            responses.append(msg)

        await app(scope, receive, send)
        result["status"] = next(
            m["status"] for m in responses if m["type"] == "http.response.start"
        )

    await _run()
    assert result["status"] == 200


# ── Contextvar isolation under concurrency ───────────────────────────────────

async def test_concurrent_requests_contextvar_isolated(pool, raw_key, raw_key_b):
    """Two concurrent requests with different keys must resolve to their respective users."""
    app = _make_test_app(lambda: pool)

    async def _get(key):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/", headers={"X-Tether-API-Key": key})

    resp_a, resp_b = await asyncio.gather(_get(raw_key), _get(raw_key_b))
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["user_id"] == TEST_USER_ID
    assert resp_b.json()["user_id"] == TEST_USER_ID_B


# ── WebSocket scope handling ─────────────────────────────────────────────────

async def test_websocket_scope_without_key_does_not_reach_inner_app():
    """WebSocket connections without an API key must be rejected — inner app must not be invoked.

    No key is present so auth fails before the pool is accessed. pool_factory
    raises if called to prove the pool is never reached.
    """
    inner_was_called = []

    async def inner_app(scope, receive, send):
        inner_was_called.append(True)

    async def pool_factory():
        raise RuntimeError("pool_factory must not be called when auth fails before key lookup")

    app = TetherAPIKeyMiddleware(inner_app, pool_factory)

    ws_scope = {
        "type": "websocket",
        "path": "/ws",
        "query_string": b"",
        "headers": [],
    }

    messages = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(msg):
        messages.append(msg)

    await app(ws_scope, receive, send)

    assert not inner_was_called, "Inner app must not be reached for unauthenticated WebSocket scopes"
