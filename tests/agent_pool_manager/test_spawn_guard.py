"""Tests for the spawn guard in _try_inject_warm.

Option C — defensive auth guard: _try_inject_warm refuses to spawn a subprocess
when options['env'] is missing or does not contain CLAUDE_CODE_OAUTH_TOKEN.

Rationale: pool subprocesses launched without OAuth credentials connect to the
Claude API without authentication and time out after 15 s (connect_timeout_seconds).
These wasted slots prevent legitimate warm subprocesses from filling the queue.
The guard blocks all hypotheses for unauthenticated spawns regardless of which
call path (RefillLoop.hint, RefillLoop.run_once, or direct _inject_warm) triggered
the spawn.

Tests:
  - No env key → returns False, no spawn, warning logged
  - env key present but CLAUDE_CODE_OAUTH_TOKEN absent → same
  - CLAUDE_CODE_OAUTH_TOKEN is empty string → same
  - CLAUDE_CODE_OAUTH_TOKEN is present and non-empty → spawn proceeds normally
  - Guard fires BEFORE the capacity check (no warming count incremented)
"""
from __future__ import annotations

import logging
import pytest
from unittest.mock import patch

from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from .fake_client import FakeClient


HASH_A = "aaa111"
OPTIONS_WITH_TOKEN = {
    "model": "claude-haiku-4-5",
    "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token-abc123"},
}
OPTIONS_NO_ENV = {"model": "claude-haiku-4-5"}
OPTIONS_EMPTY_ENV = {"model": "claude-haiku-4-5", "env": {}}
OPTIONS_EMPTY_TOKEN = {
    "model": "claude-haiku-4-5",
    "env": {"CLAUDE_CODE_OAUTH_TOKEN": ""},
}


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


# ---------------------------------------------------------------------------
# Guard: reject spawns without CLAUDE_CODE_OAUTH_TOKEN
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_guard_rejects_no_env_key():
    """_try_inject_warm returns False when options has no 'env' key."""
    pool = make_pool()
    spawned = []

    def _tracking_factory(*args, **kwargs):
        client = FakeClient()
        spawned.append(client)
        return client

    with patch("agent_pool_manager.pool.ClaudeSDKClient", side_effect=_tracking_factory):
        result = await pool._try_inject_warm(HASH_A, OPTIONS_NO_ENV)

    assert result is False, "must return False when env key absent"
    assert len(spawned) == 0, "no ClaudeSDKClient must be constructed"


@pytest.mark.asyncio
async def test_spawn_guard_rejects_empty_env():
    """_try_inject_warm returns False when env dict has no CLAUDE_CODE_OAUTH_TOKEN."""
    pool = make_pool()
    spawned = []

    def _tracking_factory(*args, **kwargs):
        client = FakeClient()
        spawned.append(client)
        return client

    with patch("agent_pool_manager.pool.ClaudeSDKClient", side_effect=_tracking_factory):
        result = await pool._try_inject_warm(HASH_A, OPTIONS_EMPTY_ENV)

    assert result is False
    assert len(spawned) == 0


@pytest.mark.asyncio
async def test_spawn_guard_rejects_empty_string_token():
    """_try_inject_warm returns False when CLAUDE_CODE_OAUTH_TOKEN is empty string."""
    pool = make_pool()
    spawned = []

    def _tracking_factory(*args, **kwargs):
        client = FakeClient()
        spawned.append(client)
        return client

    with patch("agent_pool_manager.pool.ClaudeSDKClient", side_effect=_tracking_factory):
        result = await pool._try_inject_warm(HASH_A, OPTIONS_EMPTY_TOKEN)

    assert result is False
    assert len(spawned) == 0


@pytest.mark.asyncio
async def test_spawn_guard_allows_valid_token():
    """_try_inject_warm returns True and spawns when CLAUDE_CODE_OAUTH_TOKEN is present."""
    pool = make_pool()
    spawned = []

    def _tracking_factory(*args, **kwargs):
        client = FakeClient()
        spawned.append(client)
        return client

    with patch("agent_pool_manager.pool.ClaudeSDKClient", side_effect=_tracking_factory):
        result = await pool._try_inject_warm(HASH_A, OPTIONS_WITH_TOKEN)

    assert result is True, "must return True when token is present"
    assert len(spawned) == 1, "exactly one ClaudeSDKClient must be constructed"


@pytest.mark.asyncio
async def test_spawn_guard_logs_warning_on_missing_token(caplog):
    """_try_inject_warm emits a WARNING when the spawn guard fires."""
    pool = make_pool()
    with caplog.at_level(logging.WARNING, logger="agent_pool_manager.pool"):
        with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
            await pool._try_inject_warm(HASH_A, OPTIONS_NO_ENV)

    assert any(
        "spawn_guard" in record.message and HASH_A in record.message
        for record in caplog.records
    ), f"expected spawn_guard warning with hash, got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_spawn_guard_does_not_increment_warming_count():
    """Guard fires before the warming counter increment — warm count stays 0."""
    pool = make_pool()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._try_inject_warm(HASH_A, OPTIONS_NO_ENV)

    assert pool.warming_count(HASH_A) == 0, (
        "warming count must not be incremented when guard rejects the spawn"
    )


@pytest.mark.asyncio
async def test_spawn_guard_increments_metrics_counter():
    """Each guard rejection increments PoolMetrics.spawn_guard_rejection_total.

    Critical for ops visibility — without this counter, the guard is silent in
    production and we cannot tell whether it's rejecting 1 spawn/day or 1000/min.
    """
    from agent_pool_manager.metrics import PoolMetrics

    pool = make_pool()
    metrics = PoolMetrics(pool)
    pool._metrics = metrics

    assert metrics.spawn_guard_rejection_total.value == 0

    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._try_inject_warm(HASH_A, OPTIONS_NO_ENV)
        await pool._try_inject_warm(HASH_A, OPTIONS_EMPTY_ENV)
        await pool._try_inject_warm(HASH_A, OPTIONS_EMPTY_TOKEN)
        # Valid token — should NOT increment
        await pool._try_inject_warm(HASH_A, OPTIONS_WITH_TOKEN)

    assert metrics.spawn_guard_rejection_total.value == 3, (
        "counter must increment once per guard rejection, not for valid spawns"
    )
