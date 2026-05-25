"""Regression tests for two startup bugs in agent_pool_manager:

Bug 1: CLAUDE_CODE_STREAM_CLOSE_TIMEOUT must be set in os.environ of the
       pool manager process (not just in the subprocess options env dict).
       The SDK reads this from os.environ to set _send_control_request timeout.

Bug 2: initialize_home_pool() must be called during server lifespan startup
       so that isolated HOME dirs are actually assigned to subprocesses.
       Without this, self._home_pool is always None and HOME injection never runs.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from agent_pool_manager.refill import RefillLoop
from agent_pool_manager.server import build_app


def _make_config(**overrides) -> AgentPoolConfig:
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
    return AgentPoolConfig(**defaults)


# ---------------------------------------------------------------------------
# Bug 1: CLAUDE_CODE_STREAM_CLOSE_TIMEOUT in os.environ (manager process)
# ---------------------------------------------------------------------------

def test_pool_init_sets_close_timeout_in_os_environ(monkeypatch):
    """Pool.__init__ must write CLAUDE_CODE_STREAM_CLOSE_TIMEOUT into os.environ.

    The Python SDK resolves this from os.environ at runtime — setting it only
    in the subprocess options env dict has no effect on the SDK timeout.
    """
    monkeypatch.delenv("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", raising=False)
    cfg = _make_config(initialize_timeout_ms=90000)
    Pool(cfg)
    assert "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT" in os.environ, (
        "Pool.__init__ must set CLAUDE_CODE_STREAM_CLOSE_TIMEOUT in os.environ"
    )
    assert os.environ["CLAUDE_CODE_STREAM_CLOSE_TIMEOUT"] == "90000", (
        f"Expected '90000', got {os.environ['CLAUDE_CODE_STREAM_CLOSE_TIMEOUT']!r}"
    )


def test_pool_init_does_not_override_existing_close_timeout(monkeypatch):
    """Pool.__init__ must not clobber a pre-existing CLAUDE_CODE_STREAM_CLOSE_TIMEOUT.

    Operator-set env vars take precedence over the pool config value.
    """
    monkeypatch.setenv("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "999999")
    cfg = _make_config(initialize_timeout_ms=90000)
    Pool(cfg)
    assert os.environ["CLAUDE_CODE_STREAM_CLOSE_TIMEOUT"] == "999999", (
        "Pre-existing CLAUDE_CODE_STREAM_CLOSE_TIMEOUT must not be overwritten by Pool.__init__"
    )


# ---------------------------------------------------------------------------
# Bug 2: HomeDirPool initialized in server lifespan
# ---------------------------------------------------------------------------

def test_server_lifespan_initializes_home_pool():
    """Server lifespan must call initialize_home_pool() so _home_pool is not None.

    Without this call, self._home_pool stays None in Pool and the HOME env var
    injection in _spawn_and_prime never runs — all subprocesses fall back to
    /home/tether/.claude.json with file-lock contention.

    Uses Starlette TestClient (synchronous) because it properly triggers the
    ASGI lifespan, unlike httpx AsyncClient with ASGITransport.
    """
    from agent_pool_manager.homes import HomeDirPool

    cfg = _make_config()
    pool = Pool(cfg)
    refill = RefillLoop(pool)

    # _home_pool should be None before lifespan runs
    assert pool._home_pool is None

    initialize_called = []

    async def _patched_initialize(self_):
        initialize_called.append(True)
        # Don't actually touch the filesystem in tests
        self_._home_pool = MagicMock(spec=HomeDirPool)

    app = build_app(pool=pool, refill=refill)

    with patch.object(Pool, "initialize_home_pool", _patched_initialize):
        with TestClient(app):
            pass  # lifespan runs during TestClient context

    assert initialize_called, (
        "initialize_home_pool() was never called during server lifespan startup"
    )
    assert pool._home_pool is not None, (
        "pool._home_pool must not be None after lifespan startup"
    )


@pytest.mark.asyncio
async def test_spawn_sets_home_env_when_home_pool_active():
    """When HomeDirPool is configured, _spawn_and_prime must set HOME in subprocess env.

    If initialize_home_pool() was never called (Bug 2), this HOME injection
    never happens — all subprocesses share /home/tether/.
    """
    from pathlib import Path
    from agent_pool_manager.homes import HomeDirPool

    cfg = _make_config()
    pool = Pool(cfg)

    # Manually wire up a mock home pool (simulates what lifespan fix should do)
    mock_home_pool = MagicMock(spec=HomeDirPool)
    isolated_home = Path("/var/lib/tether/claude-homes/home-0")
    mock_home_pool.acquire = AsyncMock(return_value=isolated_home)
    mock_home_pool.release = MagicMock()
    pool._home_pool = mock_home_pool

    captured_options: list[dict] = []

    def fake_build_sdk_options(options, can_use_tool=None):
        captured_options.append(dict(options))
        return MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    @asynccontextmanager
    async def _fake_get_conn(p, *, user_id=None):
        yield AsyncMock()

    options = {
        "model": "claude-haiku-4-5-20251001",
        "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"},
        "mcp_servers": ["tether"],
    }

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

    assert captured_options, "Expected _build_sdk_options to be called"
    env = captured_options[0].get("env") or {}
    assert "HOME" in env, (
        f"HOME env var missing from subprocess options; got keys: {list(env.keys())}"
    )
    assert env["HOME"] == str(isolated_home), (
        f"Expected HOME={isolated_home}, got {env.get('HOME')!r}"
    )
