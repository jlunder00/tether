"""Tests for agent_pool_manager.refill — background refill loop behavior."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch

from .fake_client import FakeClient
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from agent_pool_manager.refill import RefillLoop


def make_pool(**overrides) -> Pool:
    defaults = dict(
        target_depth_per_hash=2,
        capacity_total=8,
        max_age_seconds=600,
        refill_poll_interval=0.02,
        prime_timeout_seconds=5,
        acquire_default_timeout=1,
    )
    defaults.update(overrides)
    cfg = AgentPoolConfig(**defaults)
    return Pool(cfg)


HASH_A = "aaa111"
OPTIONS_A = {"model": "claude-haiku-4-5", "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"}}


@pytest.mark.asyncio
async def test_refill_spawns_to_target_depth():
    """RefillLoop fills warm queue to target_depth_per_hash for a registered hash."""
    pool = make_pool(target_depth_per_hash=2)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        loop = RefillLoop(pool)
        loop.register(HASH_A, OPTIONS_A)
        task = asyncio.create_task(loop.run_once())
        await asyncio.wait_for(task, timeout=2.0)

    assert pool.warm_count(HASH_A) == 2


@pytest.mark.asyncio
async def test_refill_runs_after_acquire():
    """After acquiring from a warm queue, refill replenishes it."""
    pool = make_pool(target_depth_per_hash=1)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        loop = RefillLoop(pool)
        loop.register(HASH_A, OPTIONS_A)
        # Pre-fill
        await loop.run_once()
        assert pool.warm_count(HASH_A) == 1

        # Acquire depletes
        handle_id, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0)
        assert pool.warm_count(HASH_A) == 0

        # Refill replenishes
        await loop.run_once()
        assert pool.warm_count(HASH_A) == 1


@pytest.mark.asyncio
async def test_refill_respects_capacity_total():
    """RefillLoop does not spawn beyond capacity_total."""
    pool = make_pool(target_depth_per_hash=3, capacity_total=2)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        loop = RefillLoop(pool)
        loop.register(HASH_A, OPTIONS_A)
        await loop.run_once()

    # Should cap at capacity_total, not target_depth_per_hash
    assert pool.warm_count(HASH_A) == 2


@pytest.mark.asyncio
async def test_hint_triggers_aggressive_refill():
    """hint() causes the RefillLoop to immediately refill the named hash."""
    pool = make_pool(target_depth_per_hash=2)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        loop = RefillLoop(pool)
        await loop.hint(HASH_A, OPTIONS_A)
        # hint should register and trigger a fill cycle
        await asyncio.sleep(0.1)

    assert pool.warm_count(HASH_A) == 2


@pytest.mark.asyncio
async def test_run_once_skips_empty_string_user_id():
    """run_once must not pass user_id="" to _try_inject_warm.

    Regression test: if _user_ids registry contains "" for a hash (e.g. due
    to a race or legacy write path bypassing the truthy guard in register()),
    run_once must NOT forward it — doing so reaches create_key with an empty
    UUID string and causes a PostgreSQL cast error.
    """
    pool = make_pool(target_depth_per_hash=1)
    loop = RefillLoop(pool)

    # Register hash normally, then inject "" directly to simulate the bug
    loop._registry[HASH_A] = OPTIONS_A
    loop._user_ids[HASH_A] = ""  # simulate stale/corrupt registry state

    calls: list = []

    async def _capture_inject(options_hash, options, *, user_id=None):
        calls.append(user_id)
        return False  # pretend capacity full so we don't actually spawn

    pool._try_inject_warm = _capture_inject

    await loop.run_once()

    assert calls, "run_once should have attempted injection"
    assert "" not in calls, f'user_id="" must not reach _try_inject_warm, got: {calls}'
    # Should be normalized to None (or injection skipped)
    for user_id in calls:
        assert user_id != "", f'empty string user_id leaked to inject: {user_id!r}'
