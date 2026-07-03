"""Tests for HomeDirPool — isolated per-subprocess home directory management."""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.homes import HomeDirPool
from agent_pool_manager.pool import Pool, Subprocess


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_home_pool(base_dir: str, template_dir: str, count: int = 3,
                    max_age_seconds: int = 600) -> HomeDirPool:
    cfg = AgentPoolConfig(
        capacity_total=count,
        max_age_seconds=max_age_seconds,
        target_depth_per_hash=1,
        prime_timeout_seconds=5,
        acquire_default_timeout=1,
        home_dir_base=base_dir,
        home_dir_template=template_dir,
    )
    return HomeDirPool(cfg)


def _make_pool(base_dir: str, template_dir: str, **overrides) -> Pool:
    defaults = dict(
        target_depth_per_hash=1,
        capacity_total=3,
        max_age_seconds=600,
        refill_poll_interval=2.0,
        prime_timeout_seconds=5,
        acquire_default_timeout=1,
        connect_timeout_seconds=5.0,
        home_dir_base=base_dir,
        home_dir_template=template_dir,
    )
    defaults.update(overrides)
    return Pool(AgentPoolConfig(**defaults))


# ---------------------------------------------------------------------------
# HomeDirPool unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_creates_dirs():
    """initialize() creates capacity_total subdirs under base_dir."""
    with tempfile.TemporaryDirectory() as base:
        pool = _make_home_pool(base, "/nonexistent-template", count=3)
        await pool.initialize()

        created = sorted(Path(base).iterdir())
        assert len(created) == 3
        for d in created:
            assert d.is_dir()


@pytest.mark.asyncio
async def test_initialize_seeds_from_template():
    """initialize() copies template_dir content into each home dir."""
    with (
        tempfile.TemporaryDirectory() as base,
        tempfile.TemporaryDirectory() as template,
    ):
        # Create a sentinel file in template
        (Path(template) / "sentinel.txt").write_text("hello")
        (Path(template) / "subdir").mkdir()
        (Path(template) / "subdir" / "nested.txt").write_text("nested")

        pool = _make_home_pool(base, template, count=2)
        await pool.initialize()

        for home in Path(base).iterdir():
            assert (home / "sentinel.txt").exists(), f"sentinel missing in {home}"
            assert (home / "subdir" / "nested.txt").exists(), f"nested missing in {home}"


@pytest.mark.asyncio
async def test_initialize_without_template_dir():
    """initialize() succeeds when template_dir does not exist — homes start empty."""
    with tempfile.TemporaryDirectory() as base:
        pool = _make_home_pool(base, "/nonexistent-no-template", count=2)
        # Must not raise even though template_dir doesn't exist
        await pool.initialize()
        assert pool.available_count() == 2


@pytest.mark.asyncio
async def test_acquire_returns_path():
    """acquire() returns a Path from the available pool."""
    with tempfile.TemporaryDirectory() as base:
        pool = _make_home_pool(base, "/nonexistent-template", count=2)
        await pool.initialize()

        path = await pool.acquire()
        assert isinstance(path, Path)
        assert path.is_dir()


@pytest.mark.asyncio
async def test_acquire_decrements_available():
    """acquire() reduces available count by 1."""
    with tempfile.TemporaryDirectory() as base:
        pool = _make_home_pool(base, "/nonexistent-template", count=3)
        await pool.initialize()

        assert pool.available_count() == 3
        await pool.acquire()
        assert pool.available_count() == 2
        await pool.acquire()
        assert pool.available_count() == 1


@pytest.mark.asyncio
async def test_release_returns_dir_to_pool():
    """release() puts the path back in the available queue."""
    with tempfile.TemporaryDirectory() as base:
        pool = _make_home_pool(base, "/nonexistent-template", count=2)
        await pool.initialize()

        path = await pool.acquire()
        assert pool.available_count() == 1

        pool.release(path)
        assert pool.available_count() == 2


@pytest.mark.asyncio
async def test_acquire_resets_dir_from_template():
    """acquire() resets the dir to template state before returning it."""
    with (
        tempfile.TemporaryDirectory() as base,
        tempfile.TemporaryDirectory() as template,
    ):
        (Path(template) / "config.json").write_text("{}")

        pool = _make_home_pool(base, template, count=1)
        await pool.initialize()

        path = await pool.acquire()
        # Simulate subprocess leaving state
        (path / "dirty_file.txt").write_text("leftover")
        pool.release(path)

        # Re-acquire — should be reset to template state
        path2 = await pool.acquire()
        assert path2 == path  # same dir was reused
        assert not (path2 / "dirty_file.txt").exists(), "Dir must be reset at acquire time"
        assert (path2 / "config.json").exists(), "Template file must be present after reset"


@pytest.mark.asyncio
async def test_ttl_sweep_evicts_stale_homes():
    """TTL sweep evicts homes held longer than max_age_seconds."""
    with tempfile.TemporaryDirectory() as base:
        pool = _make_home_pool(base, "/nonexistent-template", count=2, max_age_seconds=1)
        await pool.initialize()

        path = await pool.acquire()
        assert pool.available_count() == 1

        # Force expiry by manipulating internal TTL
        pool._checked_out[str(path)] = time.monotonic() - 2  # 2s in the past

        await pool.sweep()
        assert pool.available_count() == 2, "Expired home must be returned to pool after sweep"


@pytest.mark.asyncio
async def test_sweep_does_not_evict_fresh_homes():
    """Sweep must not evict homes within TTL."""
    with tempfile.TemporaryDirectory() as base:
        pool = _make_home_pool(base, "/nonexistent-template", count=2, max_age_seconds=600)
        await pool.initialize()

        await pool.acquire()
        assert pool.available_count() == 1

        await pool.sweep()
        assert pool.available_count() == 1, "Non-expired home must not be evicted"


@pytest.mark.asyncio
async def test_release_idempotent():
    """release() called twice on the same path does not double-add to queue."""
    with tempfile.TemporaryDirectory() as base:
        pool = _make_home_pool(base, "/nonexistent-template", count=2)
        await pool.initialize()

        path = await pool.acquire()
        pool.release(path)
        pool.release(path)  # second call must be a no-op
        # Queue should not exceed capacity_total
        assert pool.available_count() <= 2


# ---------------------------------------------------------------------------
# Pool integration tests — HOME env var + release on _terminate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_sets_home_env_var():
    """_spawn_and_prime sets HOME to the assigned home dir in subprocess env."""
    with (
        tempfile.TemporaryDirectory() as base,
        tempfile.TemporaryDirectory() as template,
    ):
        pool = _make_pool(base, template)
        await pool.initialize_home_pool()

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
            sub = await pool._spawn_and_prime(
                options_hash="aabbccdd",
                options={
                    "model": "claude-haiku-4-5-20251001",
                    "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test"},
                    "mcp_servers": ["tether"],
                },
                user_id="user-uuid-123",
            )

        assert captured_options, "Expected _build_sdk_options to be called"
        env = captured_options[0].get("env") or {}
        assert "HOME" in env, f"HOME missing from subprocess env; got keys: {list(env.keys())}"
        home_path = Path(env["HOME"])
        assert home_path.is_dir(), f"HOME path must be an existing directory: {home_path}"

        # Subprocess struct stores the home path
        assert sub.home_path is not None
        assert sub.home_path == home_path


@pytest.mark.asyncio
async def test_terminate_releases_home_dir():
    """_terminate returns the home dir to the home pool."""
    with (
        tempfile.TemporaryDirectory() as base,
        tempfile.TemporaryDirectory() as template,
    ):
        pool = _make_pool(base, template)
        await pool.initialize_home_pool()

        initial_available = pool._home_pool.available_count()

        # Acquire directly
        home_path = await pool._home_pool.acquire()
        assert pool._home_pool.available_count() == initial_available - 1

        mock_proc = MagicMock()
        mock_proc.disconnect = AsyncMock()

        sub = Subprocess(
            proc=mock_proc,
            options_hash="aabbccdd",
            options={},
            mcp_key_id=None,
            mcp_user_id=None,
            home_path=home_path,
        )

        await pool._terminate(sub)
        assert pool._home_pool.available_count() == initial_available, (
            "_terminate must release home_path back to home pool"
        )


@pytest.mark.asyncio
async def test_terminate_without_home_path_does_not_fail():
    """_terminate handles sub.home_path=None gracefully (no home pool configured)."""
    pool = Pool(AgentPoolConfig())  # no home dir config
    mock_proc = MagicMock()
    mock_proc.disconnect = AsyncMock()

    sub = Subprocess(
        proc=mock_proc,
        options_hash="aabbccdd",
        options={},
        home_path=None,
    )
    # Must not raise
    await pool._terminate(sub)
    mock_proc.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_spawn_without_home_pool_no_home_env():
    """When home pool is not initialized, HOME is not injected into env."""
    pool = Pool(AgentPoolConfig())  # no home dir config
    pool._home_pool = None

    captured_options: list[dict] = []

    def fake_build_sdk_options(options, can_use_tool=None):
        captured_options.append(dict(options))
        return MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    with (
        patch.object(Pool, "_build_sdk_options", side_effect=fake_build_sdk_options),
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
        patch.object(Pool, "_do_prime", new=AsyncMock()),
    ):
        sub = await pool._spawn_and_prime(
            options_hash="aabbccdd",
            options={
                "model": "claude-haiku-4-5-20251001",
                "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test"},
            },
            user_id=None,
        )

    env = (captured_options[0].get("env") or {}) if captured_options else {}
    assert "HOME" not in env, "HOME must not be injected when home pool is absent"
    assert sub.home_path is None
