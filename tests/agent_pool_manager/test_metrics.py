"""Tests for pool observability — structured logging, /metrics endpoint, token release."""
from __future__ import annotations

import asyncio
import logging
import pytest
from unittest.mock import patch, AsyncMock, call

from httpx import AsyncClient, ASGITransport

from .fake_client import FakeClient
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.metrics import PoolMetrics
from agent_pool_manager.pool import Pool
from agent_pool_manager.refill import RefillLoop
from agent_pool_manager.server import build_app


HASH_A = "aaa111"
OPTIONS_A = {"model": "claude-haiku-4-5", "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"}}
USER_ID = "user-uuid-1234"


def make_pool(**overrides) -> Pool:
    defaults = dict(
        target_depth_per_hash=2,
        capacity_total=8,
        max_age_seconds=600,
        refill_poll_interval=0.05,
        prime_timeout_seconds=5,
        acquire_default_timeout=1,
    )
    defaults.update(overrides)
    cfg = AgentPoolConfig(**defaults)
    return Pool(cfg)


@pytest.fixture
async def http_client():
    pool = make_pool()
    refill = RefillLoop(pool)
    metrics = PoolMetrics()
    app = build_app(pool=pool, refill=refill, metrics=metrics)
    # Manually initialise app state (lifespan not required for test isolation,
    # matching pattern in test_server.py) — but wire metrics into pool explicitly.
    app.state.pool = pool
    app.state.refill = refill
    app.state.metrics = metrics
    pool._metrics = metrics      # wire so acquire/release events are counted
    metrics.attach_pool(pool)    # wire so gauge render reads live pool state
    refill.start()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac, pool, metrics
    refill.stop()


# ---------------------------------------------------------------------------
# PoolMetrics unit tests
# ---------------------------------------------------------------------------

def test_metrics_counter_increments():
    """Counter.inc() increments and render_text() outputs Prometheus lines."""
    m = PoolMetrics()
    m.acquire_total.inc()
    m.acquire_total.inc()
    text = m.render_text()
    assert "pool_acquire_total 2" in text


def test_metrics_histogram_observe():
    """Histogram.observe() updates bucket counts and sum."""
    m = PoolMetrics()
    m.acquire_latency_seconds.observe(0.07)
    m.acquire_latency_seconds.observe(0.3)
    text = m.render_text()
    assert "pool_acquire_latency_seconds_count 2" in text
    assert "pool_acquire_latency_seconds_sum" in text
    # 0.07 fits in the 0.1 bucket; 0.3 fits in the 0.5 bucket
    assert 'pool_acquire_latency_seconds_bucket{le="0.1"}' in text


def test_metrics_histogram_cumulative_counts_are_monotonic_and_correct():
    """Histogram bucket cumulative values are correct — not double-counted.

    Prometheus requires cumulative semantics: each le=X bucket reports the
    count of ALL observations with value <= X. Verify exact values for a
    known set of observations to catch double-counting bugs.
    """
    m = PoolMetrics()
    # observe: 0.07 (fits ≤ 0.1), 0.3 (fits ≤ 0.5), 1.5 (fits ≤ 2.5)
    m.acquire_latency_seconds.observe(0.07)
    m.acquire_latency_seconds.observe(0.3)
    m.acquire_latency_seconds.observe(1.5)
    text = m.render_text()

    # Cumulative: le=0.025: 0, le=0.1: 1, le=0.5: 2, le=2.5: 3, +Inf: 3
    assert 'pool_acquire_latency_seconds_bucket{le="0.025"} 0.0' in text
    assert 'pool_acquire_latency_seconds_bucket{le="0.1"} 1.0' in text
    assert 'pool_acquire_latency_seconds_bucket{le="0.5"} 2.0' in text
    assert 'pool_acquire_latency_seconds_bucket{le="2.5"} 3.0' in text
    assert 'pool_acquire_latency_seconds_bucket{le="+Inf"} 3.0' in text

    assert "pool_acquire_latency_seconds_count 3.0" in text
    # sum: 0.07 + 0.3 + 1.5 = 1.87
    assert "pool_acquire_latency_seconds_sum 1.87" in text


def test_metrics_timeout_counter():
    """acquire_timeout_total increments on timeout."""
    m = PoolMetrics()
    m.acquire_timeout_total.inc()
    text = m.render_text()
    assert "pool_acquire_timeout_total 1" in text


def test_metrics_refill_counter():
    """refill_total increments on refill events."""
    m = PoolMetrics()
    m.refill_total.inc()
    m.refill_total.inc()
    text = m.render_text()
    assert "pool_refill_total 2" in text


def test_metrics_expire_counter():
    """expire_total increments on subprocess TTL expiry."""
    m = PoolMetrics()
    m.expire_total.inc()
    text = m.render_text()
    assert "pool_expire_total 1" in text


# ---------------------------------------------------------------------------
# /metrics endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text(http_client):
    """/metrics returns 200 with text/plain content-type and counter lines."""
    ac, pool, metrics = http_client
    resp = await ac.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "pool_acquire_total" in body
    assert "pool_acquire_latency_seconds" in body
    assert "pool_acquire_timeout_total" in body


@pytest.mark.asyncio
async def test_metrics_endpoint_reflects_acquire(http_client):
    """/metrics acquire_total increments after a successful acquire."""
    ac, pool, metrics = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    await ac.post("/acquire", json={
        "user_id": USER_ID,
        "options_hash": HASH_A,
        "options": OPTIONS_A,
        "timeout_seconds": 1.0,
    })

    resp = await ac.get("/metrics")
    body = resp.text
    assert "pool_acquire_total 1" in body


@pytest.mark.asyncio
async def test_metrics_endpoint_reflects_timeout(http_client):
    """/metrics acquire_timeout_total increments on PoolExhausted."""
    ac, pool, metrics = http_client
    # no warm clients → will time out
    await ac.post("/acquire", json={
        "user_id": USER_ID,
        "options_hash": HASH_A,
        "options": OPTIONS_A,
        "timeout_seconds": 0.05,
    })

    resp = await ac.get("/metrics")
    body = resp.text
    assert "pool_acquire_timeout_total 1" in body


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_emits_structured_log(http_client, caplog):
    """pool.acquire() logs user_id, options_hash, and latency_ms at INFO level."""
    ac, pool, metrics = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    with caplog.at_level(logging.INFO, logger="agent_pool_manager.pool"):
        await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0, user_id=USER_ID)

    # Should see an acquire log line with key fields
    acquire_records = [r for r in caplog.records if "acquire" in r.message.lower()]
    assert acquire_records, "Expected an acquire log record"
    log_msg = acquire_records[0].message
    assert "user_id" in log_msg or USER_ID in log_msg


@pytest.mark.asyncio
async def test_release_emits_structured_log(http_client, caplog):
    """pool.release() logs the handle_id and reusable flag at INFO level."""
    ac, pool, metrics = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0, user_id=USER_ID)

    with caplog.at_level(logging.INFO, logger="agent_pool_manager.pool"):
        await pool.release(handle_id, reusable=False)

    release_records = [r for r in caplog.records if "release" in r.message.lower()]
    assert release_records, "Expected a release log record"


@pytest.mark.asyncio
async def test_expire_emits_structured_log(caplog):
    """Expired subprocesses emit an expire log record at INFO level."""
    import time
    pool = make_pool(max_age_seconds=0)
    fake = FakeClient()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", lambda **kw: fake):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    # Force spawned_at to past
    q = pool._warm[HASH_A]
    items = []
    while not q.empty():
        items.append(await q.get())
    for sub in items:
        sub.spawned_at = time.monotonic() - 999
        await q.put(sub)

    with caplog.at_level(logging.INFO, logger="agent_pool_manager.pool"):
        try:
            await pool.acquire(HASH_A, OPTIONS_A, timeout=0.05, user_id=USER_ID)
        except Exception:
            pass

    expire_records = [r for r in caplog.records if "expir" in r.message.lower()]
    assert expire_records, "Expected an expire log record"


# ---------------------------------------------------------------------------
# Token tracking via release endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_release_with_tokens_accepted(http_client):
    """POST /handle/{id}/release with input_tokens + output_tokens returns 204."""
    ac, pool, metrics = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    acquire_resp = await ac.post("/acquire", json={
        "user_id": USER_ID,
        "options_hash": HASH_A,
        "options": OPTIONS_A,
        "timeout_seconds": 1.0,
    })
    handle_id = acquire_resp.json()["handle_id"]

    resp = await ac.post(f"/handle/{handle_id}/release", json={
        "reusable": False,
        "user_id": USER_ID,
        "input_tokens": 512,
        "output_tokens": 128,
    })
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_release_with_tokens_fires_async_write(http_client):
    """When tokens are provided on release, write_token_usage is called async."""
    ac, pool, metrics = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    acquire_resp = await ac.post("/acquire", json={
        "user_id": USER_ID,
        "options_hash": HASH_A,
        "options": OPTIONS_A,
        "timeout_seconds": 1.0,
    })
    handle_id = acquire_resp.json()["handle_id"]

    with patch("agent_pool_manager.server.write_token_usage_async") as mock_write:
        resp = await ac.post(f"/handle/{handle_id}/release", json={
            "reusable": False,
            "user_id": USER_ID,
            "input_tokens": 512,
            "output_tokens": 128,
        })
        assert resp.status_code == 204
        # Should have been called once
        mock_write.assert_called_once()
        _, kwargs = mock_write.call_args[0], mock_write.call_args[1]
        args = mock_write.call_args[0]
        # user_id, input_tokens, output_tokens must be passed
        assert USER_ID in args or USER_ID in str(mock_write.call_args)


@pytest.mark.asyncio
async def test_release_without_tokens_does_not_write(http_client):
    """When no tokens provided on release, write_token_usage is NOT called."""
    ac, pool, metrics = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    acquire_resp = await ac.post("/acquire", json={
        "user_id": USER_ID,
        "options_hash": HASH_A,
        "options": OPTIONS_A,
        "timeout_seconds": 1.0,
    })
    handle_id = acquire_resp.json()["handle_id"]

    with patch("agent_pool_manager.server.write_token_usage_async") as mock_write:
        resp = await ac.post(f"/handle/{handle_id}/release", json={"reusable": False})
        assert resp.status_code == 204
        mock_write.assert_not_called()
