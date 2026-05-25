"""Diagnostic logging tests — verify INFO logs are emitted on the warm spawn path.

This is a DIAGNOSTIC INSTRUMENTATION PR.  The 15s warm-spawn timeout in
prod has an unknown root cause: the MCP 401 hypothesis is unverified, and
the fly.io container has no ``~/.claude/mcp.json`` provisioned.  Before
writing any fix, we need visibility into what the spawn path actually
does.  These tests pin the new INFO-level log markers so they can't
silently regress.

All assertions check for log MARKERS (substring tokens), not exact phrasing,
so future log-line wording changes don't break the tests.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from agent_pool_manager.refill import RefillLoop
from .fake_client import FakeClient


HASH_A = "diag111"
OPTIONS_VALID = {
    "model": "claude-haiku-4-5-20251001",
    "mcp_servers": ["tether"],
    "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token-abc123"},
}


def _make_pool() -> Pool:
    cfg = AgentPoolConfig(
        target_depth_per_hash=2,
        capacity_total=8,
        max_age_seconds=600,
        refill_poll_interval=0.05,
        prime_timeout_seconds=5,
        acquire_default_timeout=1,
        connect_timeout_seconds=5,
    )
    return Pool(cfg)


# ---------------------------------------------------------------------------
# pool._spawn_and_prime
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_and_prime_logs_options_summary(caplog):
    """_spawn_and_prime must log a summary of options before connect()."""
    pool = _make_pool()
    with caplog.at_level(logging.INFO, logger="agent_pool_manager.pool"):
        with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
            await pool._try_inject_warm(HASH_A, OPTIONS_VALID)

    messages = [r.message for r in caplog.records]
    # Marker for the options summary log
    assert any("pool.spawn_start" in m and HASH_A in m for m in messages), (
        f"expected pool.spawn_start log, got: {messages}"
    )


@pytest.mark.asyncio
async def test_spawn_and_prime_logs_env_keys_redacted(caplog):
    """The env key summary must NOT leak the OAuth token value."""
    pool = _make_pool()
    with caplog.at_level(logging.INFO, logger="agent_pool_manager.pool"):
        with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
            await pool._try_inject_warm(HASH_A, OPTIONS_VALID)

    full_log_text = "\n".join(r.message for r in caplog.records)
    # The full token value must NOT appear anywhere in the logs
    assert "sk-ant-test-token-abc123" not in full_log_text, (
        "OAuth token leaked into logs — must be redacted"
    )
    # But the env key NAME should appear so we know what's in the env
    assert "CLAUDE_CODE_OAUTH_TOKEN" in full_log_text, (
        "env keys must be listed so we can see what's in the subprocess env"
    )


@pytest.mark.asyncio
async def test_spawn_and_prime_logs_mcp_servers_form(caplog):
    """The MCP servers form (list/dict/path/empty) must be logged."""
    pool = _make_pool()
    with caplog.at_level(logging.INFO, logger="agent_pool_manager.pool"):
        with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
            await pool._try_inject_warm(HASH_A, OPTIONS_VALID)

    full_log_text = "\n".join(r.message for r in caplog.records)
    # Marker — should indicate the type/form of mcp_servers
    assert "mcp_servers" in full_log_text, (
        f"mcp_servers form must be logged, got: {full_log_text}"
    )


@pytest.mark.asyncio
async def test_spawn_and_prime_logs_connect_timing(caplog):
    """Timing checkpoints around client.connect() must be logged."""
    pool = _make_pool()
    with caplog.at_level(logging.INFO, logger="agent_pool_manager.pool"):
        with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
            await pool._try_inject_warm(HASH_A, OPTIONS_VALID)

    messages = [r.message for r in caplog.records]
    assert any("pool.connect_done" in m and HASH_A in m for m in messages), (
        f"expected pool.connect_done log, got: {messages}"
    )


@pytest.mark.asyncio
async def test_spawn_and_prime_logs_connect_failure_details(caplog):
    """On connect failure, log the exception type, time spent, and PID if available."""
    pool = _make_pool()

    class FailingClient(FakeClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.fail_connect = True

    with caplog.at_level(logging.INFO, logger="agent_pool_manager.pool"):
        with patch("agent_pool_manager.pool.ClaudeSDKClient", FailingClient):
            with pytest.raises(Exception):
                await pool._try_inject_warm(HASH_A, OPTIONS_VALID)

    full_log_text = "\n".join(r.message for r in caplog.records)
    assert "pool.connect_failed" in full_log_text, (
        f"expected pool.connect_failed log, got: {full_log_text}"
    )
    # Must include the exception class name
    assert "RuntimeError" in full_log_text


# ---------------------------------------------------------------------------
# pool._build_sdk_options
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_sdk_options_logs_filtered_fields(caplog):
    """When _build_sdk_options drops unknown keys, log which ones were dropped."""
    pool = _make_pool()
    # Include a key that's NOT in ClaudeAgentOptions to force filtering
    options = {
        **OPTIONS_VALID,
        "_internal_unknown_key": "this should be filtered",
    }
    with caplog.at_level(logging.INFO, logger="agent_pool_manager.pool"):
        with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
            await pool._try_inject_warm(HASH_A, options)

    full_log_text = "\n".join(r.message for r in caplog.records)
    assert "pool.sdk_options" in full_log_text, (
        f"expected pool.sdk_options log listing fields, got: {full_log_text}"
    )


# ---------------------------------------------------------------------------
# refill.RefillLoop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refill_hint_logs_registration(caplog):
    """RefillLoop.hint must log the hash, deficit, and registry size."""
    pool = _make_pool()
    loop = RefillLoop(pool)

    with caplog.at_level(logging.INFO, logger="agent_pool_manager.refill"):
        with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
            await loop.hint(HASH_A, OPTIONS_VALID)
            # Let the create_task spawns settle
            import asyncio as _asyncio
            await _asyncio.sleep(0.01)

    messages = [r.message for r in caplog.records]
    assert any("refill.hint" in m and HASH_A in m for m in messages), (
        f"expected refill.hint log, got: {messages}"
    )
