"""Tests for configurable initialize_timeout_ms — CLAUDE_CODE_STREAM_CLOSE_TIMEOUT injection."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool


def _make_pool(**overrides) -> Pool:
    defaults = dict(
        target_depth_per_hash=1,
        capacity_total=4,
        max_age_seconds=600,
        refill_poll_interval=2.0,
        prime_timeout_seconds=5,
        acquire_default_timeout=1,
        connect_timeout_seconds=5.0,
    )
    defaults.update(overrides)
    cfg = AgentPoolConfig(**defaults)
    return Pool(cfg)


def _base_options() -> dict:
    return {
        "model": "claude-haiku-4-5-20251001",
        "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"},
        "mcp_servers": ["tether"],
    }


@pytest.mark.asyncio
async def test_initialize_timeout_injected_into_env():
    """CLAUDE_CODE_STREAM_CLOSE_TIMEOUT must be set in subprocess env from config."""
    pool = _make_pool(initialize_timeout_ms=180000)

    captured_options: list[dict] = []

    def fake_build_sdk_options(options, can_use_tool=None):
        captured_options.append(dict(options))
        return MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    @asynccontextmanager
    async def _fake_get_conn(p, *, user_id=None):
        yield AsyncMock()

    with (
        patch("db.postgres.get_conn", side_effect=_fake_get_conn),
        patch(
            "db.pg_queries.api_keys.create_key",
            new=AsyncMock(return_value=("ttr_fake", {"id": "k1"})),
        ),
        patch.object(Pool, "_build_sdk_options", side_effect=fake_build_sdk_options),
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
        patch.object(Pool, "_do_prime", new=AsyncMock()),
    ):
        await pool._spawn_and_prime(
            options_hash="aabbccdd",
            options=_base_options(),
            user_id="user-uuid-123",
        )

    assert captured_options, "Expected _build_sdk_options to be called"
    env = captured_options[0].get("env") or {}
    assert "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT" in env, (
        f"CLAUDE_CODE_STREAM_CLOSE_TIMEOUT missing from env; got keys: {list(env.keys())}"
    )
    assert env["CLAUDE_CODE_STREAM_CLOSE_TIMEOUT"] == "180000", (
        f"Expected '180000', got {env['CLAUDE_CODE_STREAM_CLOSE_TIMEOUT']!r}"
    )


@pytest.mark.asyncio
async def test_initialize_timeout_uses_default():
    """Default initialize_timeout_ms=120000 is injected when not overridden."""
    pool = _make_pool()  # default: 120000

    captured_options: list[dict] = []

    def fake_build_sdk_options(options, can_use_tool=None):
        captured_options.append(dict(options))
        return MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    @asynccontextmanager
    async def _fake_get_conn(p, *, user_id=None):
        yield AsyncMock()

    with (
        patch("db.postgres.get_conn", side_effect=_fake_get_conn),
        patch(
            "db.pg_queries.api_keys.create_key",
            new=AsyncMock(return_value=("ttr_fake", {"id": "k1"})),
        ),
        patch.object(Pool, "_build_sdk_options", side_effect=fake_build_sdk_options),
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
        patch.object(Pool, "_do_prime", new=AsyncMock()),
    ):
        await pool._spawn_and_prime(
            options_hash="aabbccdd",
            options=_base_options(),
            user_id="user-uuid-123",
        )

    env = (captured_options[0].get("env") or {}) if captured_options else {}
    assert env.get("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT") == "120000", (
        f"Expected default '120000', got {env.get('CLAUDE_CODE_STREAM_CLOSE_TIMEOUT')!r}"
    )


@pytest.mark.asyncio
async def test_initialize_timeout_does_not_override_caller_value():
    """If the caller already set CLAUDE_CODE_STREAM_CLOSE_TIMEOUT, we must not clobber it."""
    pool = _make_pool(initialize_timeout_ms=120000)

    options = dict(_base_options())
    options["env"] = dict(options["env"])
    options["env"]["CLAUDE_CODE_STREAM_CLOSE_TIMEOUT"] = "999999"

    captured_options: list[dict] = []

    def fake_build_sdk_options(o, can_use_tool=None):
        captured_options.append(dict(o))
        return MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    @asynccontextmanager
    async def _fake_get_conn(p, *, user_id=None):
        yield AsyncMock()

    with (
        patch("db.postgres.get_conn", side_effect=_fake_get_conn),
        patch(
            "db.pg_queries.api_keys.create_key",
            new=AsyncMock(return_value=("ttr_fake", {"id": "k1"})),
        ),
        patch.object(Pool, "_build_sdk_options", side_effect=fake_build_sdk_options),
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
        patch.object(Pool, "_do_prime", new=AsyncMock()),
    ):
        await pool._spawn_and_prime(
            options_hash="aabbccdd",
            options=options,
            user_id="user-uuid-123",
        )

    env = (captured_options[0].get("env") or {}) if captured_options else {}
    assert env.get("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT") == "999999", (
        "Caller-supplied CLAUDE_CODE_STREAM_CLOSE_TIMEOUT must not be overridden"
    )


def test_initialize_timeout_ms_field_exists():
    """AgentPoolConfig must have initialize_timeout_ms field with default 120000."""
    cfg = AgentPoolConfig()
    assert hasattr(cfg, "initialize_timeout_ms"), "Field initialize_timeout_ms missing from AgentPoolConfig"
    assert cfg.initialize_timeout_ms == 120000, (
        f"Default should be 120000, got {cfg.initialize_timeout_ms}"
    )


def test_initialize_timeout_ms_configurable():
    """AgentPoolConfig accepts initialize_timeout_ms override."""
    cfg = AgentPoolConfig(initialize_timeout_ms=60000)
    assert cfg.initialize_timeout_ms == 60000
