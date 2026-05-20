"""Tests for agent_pool_manager.refill — background refill loop behavior."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch

from .fake_client import FakeClient
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool, PoolExhausted
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
OPTIONS_A = {"model": "claude-haiku-4-5"}


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
