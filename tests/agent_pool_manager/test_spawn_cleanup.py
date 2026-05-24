"""Tests for subprocess cleanup in _spawn_and_prime on connect() failure.

Verifies that:
  - When connect() raises, the underlying subprocess is killed
  - kill() and wait() are both called (not just kill — we need to reap the process)
  - The original exception is re-raised so the caller can handle it
  - When connect() times out, same cleanup applies
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from .fake_client import FakeClient


HASH_A = "aaa111"
OPTIONS_A = {"model": "claude-haiku-4-5", "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"}}


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


class _FakeClientWithProcess(FakeClient):
    """FakeClient that exposes a mock _transport._process for cleanup testing."""

    def __init__(self, *, fail_connect: bool = False, connect_delay: float = 0.0):
        super().__init__(fail_connect=fail_connect)
        self.connect_delay = connect_delay
        # Simulate the subprocess handle the pool cleanup code accesses
        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_transport = MagicMock()
        mock_transport._process = mock_proc
        self._transport = mock_transport

    @property
    def mock_proc(self):
        return self._transport._process


@pytest.mark.asyncio
async def test_connect_failure_kills_subprocess():
    """When connect() raises, _spawn_and_prime must call kill() on the subprocess."""
    pool = make_pool()
    client = _FakeClientWithProcess(fail_connect=True)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=client):
        with pytest.raises(RuntimeError, match="connect failed"):
            await pool._spawn_and_prime(HASH_A, OPTIONS_A)

    client.mock_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_connect_failure_awaits_process_wait():
    """After kill(), wait() must be awaited to reap the zombie process."""
    pool = make_pool()
    client = _FakeClientWithProcess(fail_connect=True)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=client):
        with pytest.raises(RuntimeError):
            await pool._spawn_and_prime(HASH_A, OPTIONS_A)

    client.mock_proc.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_failure_reraises_original_exception():
    """The original connect() exception must propagate so refill knows the spawn failed."""
    pool = make_pool()
    client = _FakeClientWithProcess(fail_connect=True)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=client):
        with pytest.raises(RuntimeError, match="connect failed"):
            await pool._spawn_and_prime(HASH_A, OPTIONS_A)


@pytest.mark.asyncio
async def test_connect_timeout_kills_subprocess():
    """When connect() times out, cleanup must still kill the subprocess."""
    pool = make_pool(connect_timeout_seconds=0.01)
    # Client delays longer than timeout
    client = _FakeClientWithProcess(connect_delay=1.0)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=client):
        with pytest.raises((asyncio.TimeoutError, Exception)):
            await pool._spawn_and_prime(HASH_A, OPTIONS_A)

    client.mock_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_successful_connect_does_not_kill_subprocess():
    """When connect() succeeds, kill() must NOT be called."""
    pool = make_pool()
    client = _FakeClientWithProcess(fail_connect=False)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=client):
        sub = await pool._spawn_and_prime(HASH_A, OPTIONS_A)

    assert sub is not None
    client.mock_proc.kill.assert_not_called()
