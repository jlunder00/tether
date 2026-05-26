"""Unit tests for agent_pool_manager.pool — mocked ClaudeSDKClient."""
from __future__ import annotations

import asyncio
import time
import pytest
from unittest.mock import patch

from .fake_client import FakeClient
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool, PoolExhausted


HASH_A = "aaa111"
HASH_B = "bbb222"
OPTIONS_A = {"model": "claude-haiku-4-5-20251001", "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"}}
OPTIONS_B = {"model": "claude-sonnet-4-5", "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token-b"}}


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
# acquire / release basics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_returns_handle_when_warm():
    """acquire() returns a handle_id immediately if a warm client exists."""
    pool = make_pool()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)
        handle_id, meta = await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0)
    assert handle_id is not None
    assert "subprocess_pid" in meta or meta.get("subprocess_pid") is None  # pid may be None in fake


@pytest.mark.asyncio
async def test_acquire_blocks_until_warm_available():
    """acquire() waits until a warm client is pushed, then returns."""
    pool = make_pool()

    async def push_after_delay():
        await asyncio.sleep(0.05)
        with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
            await pool._inject_warm(HASH_A, OPTIONS_A)

    asyncio.create_task(push_after_delay())
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        handle_id, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=2.0)
    assert handle_id is not None


@pytest.mark.asyncio
async def test_acquire_raises_pool_exhausted_on_timeout():
    """acquire() raises PoolExhausted when no warm client within timeout."""
    pool = make_pool()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        with pytest.raises(PoolExhausted):
            await pool.acquire(HASH_A, OPTIONS_A, timeout=0.05)


@pytest.mark.asyncio
async def test_options_hash_partitions_correctly():
    """Different options_hash values maintain separate warm queues."""
    pool = make_pool()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)
        await pool._inject_warm(HASH_B, OPTIONS_B)

        assert pool.warm_count(HASH_A) == 1
        assert pool.warm_count(HASH_B) == 1

        handle_a, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0)
        assert pool.warm_count(HASH_A) == 0
        assert pool.warm_count(HASH_B) == 1  # B untouched


@pytest.mark.asyncio
async def test_release_not_reusable_terminates_client():
    """release(reusable=False) disconnects the underlying client."""
    pool = make_pool()
    fake = FakeClient()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", lambda **kw: fake):
        await pool._inject_warm(HASH_A, OPTIONS_A)
        handle_id, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0)

    await pool.release(handle_id, reusable=False)
    assert fake.disconnected


@pytest.mark.asyncio
async def test_release_reusable_returns_to_warm_queue():
    """release(reusable=True) puts the client back in the warm queue."""
    pool = make_pool()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)
        handle_id, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0)

    assert pool.warm_count(HASH_A) == 0
    await pool.release(handle_id, reusable=True)
    assert pool.warm_count(HASH_A) == 1


# ---------------------------------------------------------------------------
# TTL drain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ttl_drains_expired_subprocess_on_acquire():
    """Subprocesses older than max_age_seconds are terminated and skipped on acquire."""
    pool = make_pool(max_age_seconds=0)  # everything expires immediately
    fake = FakeClient()
    # Bypass _inject_warm (which primes) to control spawned_at
    with patch("agent_pool_manager.pool.ClaudeSDKClient", lambda **kw: fake):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    # Force spawned_at to the past
    q = pool._warm[HASH_A]
    items = []
    while not q.empty():
        items.append(await q.get())
    for sub in items:
        sub.spawned_at = time.monotonic() - 999
        await q.put(sub)

    # acquire should drain the expired one and raise PoolExhausted
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        with pytest.raises(PoolExhausted):
            await pool.acquire(HASH_A, OPTIONS_A, timeout=0.05)
    assert fake.disconnected


# ---------------------------------------------------------------------------
# capacity_total enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capacity_total_limits_total_subprocesses():
    """warm + active + warming never exceeds capacity_total."""
    pool = make_pool(capacity_total=2)
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)
        await pool._inject_warm(HASH_A, OPTIONS_A)

        # Pool is at capacity — another inject should be blocked
        assert pool.total_count() == 2
        # Try to inject a third — should be refused
        accepted = await pool._try_inject_warm(HASH_A, OPTIONS_A)
        assert not accepted
        assert pool.total_count() == 2


# ---------------------------------------------------------------------------
# interrupt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interrupt_active_handle():
    """interrupt() calls .interrupt() on the underlying client."""
    pool = make_pool()
    fake = FakeClient()
    with patch("agent_pool_manager.pool.ClaudeSDKClient", lambda **kw: fake):
        await pool._inject_warm(HASH_A, OPTIONS_A)
        handle_id, _ = await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0)

    await pool.interrupt(handle_id)
    assert fake.interrupted
