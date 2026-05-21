"""Tests for agent_pool_manager.client — PoolClient HTTP wrapper."""
from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import ASGITransport

from .fake_client import FakeClient
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from agent_pool_manager.refill import RefillLoop
from agent_pool_manager.server import build_app
from agent_pool_manager.client import PoolClient, PoolClientError


HASH_A = "abc123"
OPTIONS_A = {"model": "claude-haiku-4-5"}
USER_ID = "user-test-1"


@pytest.fixture
async def pool_and_app():
    """In-process pool + FastAPI app for round-trip tests."""
    cfg = AgentPoolConfig(
        target_depth_per_hash=2,
        capacity_total=8,
        max_age_seconds=600,
        refill_poll_interval=0.05,
        prime_timeout_seconds=5,
        acquire_default_timeout=2,
    )
    pool = Pool(cfg)
    refill = RefillLoop(pool)
    app = build_app(pool=pool, refill=refill)
    app.state.pool = pool
    app.state.refill = refill
    refill.start()
    yield pool, app
    refill.stop()


@pytest.fixture
async def http_client(pool_and_app):
    """PoolClient backed by an in-process FastAPI app."""
    pool, app = pool_and_app
    transport = ASGITransport(app=app)
    client = PoolClient(base_url="http://test", _transport=transport)
    try:
        yield client, pool
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# acquire / release
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_returns_handle(http_client):
    """PoolClient.acquire() returns a handle_id when warm client available."""
    client, pool = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id = await client.acquire(USER_ID, HASH_A, OPTIONS_A, timeout_seconds=2.0)
    assert handle_id is not None
    assert isinstance(handle_id, str)


@pytest.mark.asyncio
async def test_acquire_raises_on_pool_exhausted(http_client):
    """PoolClient.acquire() raises PoolClientError when pool is exhausted."""
    client, pool = http_client

    with pytest.raises(PoolClientError, match="pool_exhausted"):
        await client.acquire(USER_ID, HASH_A, OPTIONS_A, timeout_seconds=0.05)


@pytest.mark.asyncio
async def test_release_after_acquire(http_client):
    """PoolClient.release() succeeds after a valid acquire."""
    client, pool = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id = await client.acquire(USER_ID, HASH_A, OPTIONS_A, timeout_seconds=2.0)
    # Should not raise
    await client.release(handle_id, reusable=False)


@pytest.mark.asyncio
async def test_release_reusable(http_client):
    """PoolClient.release(reusable=True) returns client to warm queue."""
    client, pool = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id = await client.acquire(USER_ID, HASH_A, OPTIONS_A, timeout_seconds=2.0)
    assert pool.warm_count(HASH_A) == 0
    await client.release(handle_id, reusable=True)
    assert pool.warm_count(HASH_A) == 1


# ---------------------------------------------------------------------------
# interrupt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interrupt_active_handle(http_client):
    """PoolClient.interrupt() sends interrupt to the active subprocess."""
    client, pool = http_client
    fake = FakeClient()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", lambda **kw: fake):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id = await client.acquire(USER_ID, HASH_A, OPTIONS_A, timeout_seconds=2.0)
    await client.interrupt(handle_id)
    assert fake.interrupted


@pytest.mark.asyncio
async def test_interrupt_unknown_handle_raises(http_client):
    """PoolClient.interrupt() raises PoolClientError for unknown handle."""
    client, pool = http_client

    with pytest.raises(PoolClientError):
        await client.interrupt("no-such-handle")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_returns_counts(http_client):
    """PoolClient.status() returns pool-wide counts."""
    client, pool = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    status = await client.status()
    assert "total_warm" in status
    assert "total_active" in status
    assert "capacity_total" in status
    assert status["total_warm"] >= 1


# ---------------------------------------------------------------------------
# hint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hint_accepted(http_client):
    """PoolClient.hint() completes without error."""
    client, pool = http_client
    # Should not raise
    await client.hint(USER_ID, HASH_A, OPTIONS_A)


# ---------------------------------------------------------------------------
# query_stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_stream_yields_events(http_client):
    """PoolClient.query_stream() yields SSE events from the pool service."""
    client, pool = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id = await client.acquire(USER_ID, HASH_A, OPTIONS_A, timeout_seconds=2.0)
    events = []
    async for event in client.query_stream(handle_id, "say hello"):
        events.append(event)
        if len(events) >= 2:
            break

    assert len(events) >= 1
    await client.release(handle_id, reusable=False)


@pytest.mark.asyncio
async def test_query_stream_unknown_handle_raises(http_client):
    """PoolClient.query_stream() raises PoolClientError for unknown handle."""
    client, pool = http_client

    with pytest.raises(PoolClientError):
        async for _ in client.query_stream("bad-handle", "hello"):
            pass
