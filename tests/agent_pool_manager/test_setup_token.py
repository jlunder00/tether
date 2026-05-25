"""Tests for POST /setup-token in agent_pool_manager.server."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from agent_pool_manager.refill import RefillLoop
from agent_pool_manager.server import build_app


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
    app.state.pool = pool
    app.state.refill = refill
    refill.start()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, pool, refill
    refill.stop()


@pytest.mark.asyncio
async def test_setup_token_returns_url_and_session(client_and_pool):
    """POST /setup-token returns auth URL and session_id when pexpect succeeds."""
    ac, pool, refill = client_and_pool
    fake_child = MagicMock()
    fake_url = "https://console.anthropic.com/oauth/authorize?code=abc"

    with patch("agent_pool_manager.server._start_pexpect_sync", return_value=(fake_child, fake_url)):
        resp = await ac.post("/setup-token", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == fake_url
    assert "session_id" in body


@pytest.mark.asyncio
async def test_setup_token_returns_503_when_pexpect_fails(client_and_pool):
    """POST /setup-token returns 503 when pexpect fails to extract a URL."""
    ac, pool, refill = client_and_pool

    with patch("agent_pool_manager.server._start_pexpect_sync", return_value=(None, None)):
        resp = await ac.post("/setup-token", json={})

    assert resp.status_code == 503
    assert "error" in resp.json()


@pytest.mark.asyncio
async def test_setup_token_complete_sends_code(client_and_pool):
    """POST /setup-token/complete sends the OAuth code and returns token."""
    ac, pool, refill = client_and_pool
    fake_child = MagicMock()
    fake_url = "https://console.anthropic.com/oauth/authorize?code=abc"
    fake_token = "sk-ant-oat-fake-token"

    with patch("agent_pool_manager.server._start_pexpect_sync", return_value=(fake_child, fake_url)):
        start_resp = await ac.post("/setup-token", json={})
    session_id = start_resp.json()["session_id"]

    with patch("agent_pool_manager.server._complete_pexpect_sync", return_value=("ok", fake_token)):
        complete_resp = await ac.post("/setup-token/complete", json={
            "session_id": session_id,
            "code": "oauth-code-here",
        })

    assert complete_resp.status_code == 200
    body = complete_resp.json()
    assert body.get("result") == "ok"
    assert body.get("token") == fake_token


@pytest.mark.asyncio
async def test_setup_token_complete_unknown_session(client_and_pool):
    """POST /setup-token/complete with unknown session_id returns 404."""
    ac, pool, refill = client_and_pool
    resp = await ac.post("/setup-token/complete", json={
        "session_id": "does-not-exist",
        "code": "whatever",
    })
    assert resp.status_code == 404
