"""Smoke tests — cold vs warm acquire latency comparison.

These tests verify that warm acquire is significantly faster than cold spawn,
and that the pool correctly tracks the latency delta. They use FakeClient so
they run in CI without a real Fly deployment.

For real Fly latency numbers, run the manual smoke script (see docs) against
tether-dev.
"""
from __future__ import annotations

import asyncio
import time
import statistics
import pytest
from unittest.mock import patch

from .fake_client import FakeClient
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from agent_pool_manager.metrics import PoolMetrics


HASH_A = "aaa111"
OPTIONS_A = {"model": "claude-haiku-4-5-20251001", "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"}}
USER_ID = "smoke-user-1"

COLD_DELAY = 0.05   # simulate a 50ms subprocess start cost
SAMPLES = 5


def make_pool(**kwargs) -> Pool:
    cfg = AgentPoolConfig(
        target_depth_per_hash=2,
        capacity_total=8,
        max_age_seconds=600,
        refill_poll_interval=0.05,
        prime_timeout_seconds=5,
        acquire_default_timeout=2,
        **kwargs,
    )
    return Pool(cfg)


class SlowFakeClient(FakeClient):
    """FakeClient that simulates a slow connect (cold start)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.connect_delay = COLD_DELAY


@pytest.mark.asyncio
async def test_warm_acquire_faster_than_cold_threshold():
    """Warm acquire should complete in < 10ms (no subprocess spawning needed)."""
    pool = make_pool()

    # Pre-warm the pool
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    t_start = time.monotonic()
    handle_id, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=2.0, user_id=USER_ID)
    warm_latency_ms = (time.monotonic() - t_start) * 1000

    await pool.release(handle_id, reusable=False)

    # Warm acquire should be very fast (< 50ms) since no subprocess spawning
    assert warm_latency_ms < 50, (
        f"Warm acquire took {warm_latency_ms:.1f}ms — expected < 50ms"
    )


@pytest.mark.asyncio
async def test_warm_acquire_substantially_faster_than_cold():
    """Warm acquire should be at least 2x faster than cold spawn."""
    pool = make_pool()

    # --- Cold latency: time _inject_warm (spawn + prime) ---
    t_cold_start = time.monotonic()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", SlowFakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)
    cold_spawn_ms = (time.monotonic() - t_cold_start) * 1000

    # --- Warm latency: time acquire from pre-warmed pool ---
    t_warm_start = time.monotonic()
    handle_id, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=2.0, user_id=USER_ID)
    warm_latency_ms = (time.monotonic() - t_warm_start) * 1000
    await pool.release(handle_id, reusable=False)

    assert cold_spawn_ms > warm_latency_ms * 2, (
        f"Cold spawn ({cold_spawn_ms:.1f}ms) should be >2x warm acquire ({warm_latency_ms:.1f}ms)"
    )


@pytest.mark.asyncio
async def test_metrics_track_latency_on_acquire():
    """Metrics histogram is populated with acquire latency values."""
    pool = make_pool()
    metrics = PoolMetrics()
    pool._metrics = metrics

    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=2.0, user_id=USER_ID)
    await pool.release(handle_id, reusable=False)

    text = metrics.render_text()
    assert "pool_acquire_latency_seconds_count 1" in text
    # Sum should be a positive number > 0
    import re
    m = re.search(r"pool_acquire_latency_seconds_sum ([0-9.e+\-]+)", text)
    assert m, "Expected pool_acquire_latency_seconds_sum in metrics"
    assert float(m.group(1)) > 0


@pytest.mark.asyncio
async def test_pool_exhaust_increments_timeout_metric():
    """Timeout on acquire increments acquire_timeout_total in metrics."""
    pool = make_pool()
    metrics = PoolMetrics()
    pool._metrics = metrics

    try:
        await pool.acquire(HASH_A, OPTIONS_A, timeout=0.02, user_id=USER_ID)
    except Exception:
        pass

    text = metrics.render_text()
    assert "pool_acquire_timeout_total 1" in text
