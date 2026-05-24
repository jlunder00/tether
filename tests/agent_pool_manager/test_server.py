"""HTTP integration tests for agent_pool_manager.server — FastAPI TestClient."""
from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from .fake_client import FakeClient
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from agent_pool_manager.refill import RefillLoop
from agent_pool_manager.server import build_app


HASH_A = "aaa111"
OPTIONS_A = {"model": "claude-haiku-4-5", "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"}}


def make_pool(**kwargs) -> Pool:
    cfg = AgentPoolConfig(
        target_depth_per_hash=2,
        capacity_total=8,
        max_age_seconds=600,
        refill_poll_interval=0.05,
        prime_timeout_seconds=5,
        acquire_default_timeout=1,
        **kwargs,
    )
    return Pool(cfg)


@pytest.fixture
async def client_and_pool():
    pool = make_pool()
    refill = RefillLoop(pool)
    app = build_app(pool=pool, refill=refill)
    # Manually initialise app state so lifespan isn't required for test isolation
    app.state.pool = pool
    app.state.refill = refill
    refill.start()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, pool, refill
    refill.stop()


@pytest.mark.asyncio
async def test_acquire_returns_handle(client_and_pool):
    """POST /acquire returns a handle_id when a warm client is available."""
    ac, pool, refill = client_and_pool
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    resp = await ac.post("/acquire", json={
        "user_id": "user-1",
        "options_hash": HASH_A,
        "options": OPTIONS_A,
        "timeout_seconds": 1.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "handle_id" in body
    assert "ready_at" in body


@pytest.mark.asyncio
async def test_acquire_pool_exhausted(client_and_pool):
    """POST /acquire returns pool_exhausted when no warm client within timeout."""
    ac, pool, refill = client_and_pool
    resp = await ac.post("/acquire", json={
        "user_id": "user-1",
        "options_hash": HASH_A,
        "options": OPTIONS_A,
        "timeout_seconds": 0.05,
    })
    assert resp.status_code == 503
    body = resp.json()
    assert body.get("error") == "pool_exhausted"
    assert "retry_after_seconds" in body


@pytest.mark.asyncio
async def test_status_returns_counts(client_and_pool):
    """GET /status returns per-partition warm/active/warming counts."""
    ac, pool, refill = client_and_pool
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    resp = await ac.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "partitions" in body
    assert "total_warm" in body
    assert "total_active" in body
    assert "capacity_total" in body
    assert body["total_warm"] >= 1


@pytest.mark.asyncio
async def test_release_endpoint(client_and_pool):
    """POST /handle/{id}/release returns 204."""
    ac, pool, refill = client_and_pool
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    acquire_resp = await ac.post("/acquire", json={
        "user_id": "user-1",
        "options_hash": HASH_A,
        "options": OPTIONS_A,
        "timeout_seconds": 1.0,
    })
    handle_id = acquire_resp.json()["handle_id"]

    resp = await ac.post(f"/handle/{handle_id}/release", json={"reusable": False})
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_interrupt_endpoint(client_and_pool):
    """POST /handle/{id}/interrupt returns 204."""
    ac, pool, refill = client_and_pool
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    acquire_resp = await ac.post("/acquire", json={
        "user_id": "user-1",
        "options_hash": HASH_A,
        "options": OPTIONS_A,
        "timeout_seconds": 1.0,
    })
    handle_id = acquire_resp.json()["handle_id"]

    resp = await ac.post(f"/handle/{handle_id}/interrupt")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_hint_endpoint(client_and_pool):
    """POST /hint returns 202 and triggers refill registration."""
    ac, pool, refill = client_and_pool
    resp = await ac.post("/hint", json={
        "user_id": "user-1",
        "options_hash": HASH_A,
        "options": OPTIONS_A,
    })
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_release_unknown_handle_returns_404(client_and_pool):
    """POST /handle/{unknown}/release returns 404."""
    ac, pool, refill = client_and_pool
    resp = await ac.post("/handle/does-not-exist/release", json={"reusable": False})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_interrupt_unknown_handle_returns_404(client_and_pool):
    """POST /handle/{unknown}/interrupt returns 404."""
    ac, pool, refill = client_and_pool
    resp = await ac.post("/handle/does-not-exist/interrupt")
    assert resp.status_code == 404
