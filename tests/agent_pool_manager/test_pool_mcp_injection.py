"""Tests for pool-side MCP placeholder injection and key lifecycle.

Covers:
  - _expand_mcp_placeholders: list-form → dict, dict passthrough, None passthrough
  - _spawn_and_prime: ephemeral key created, options expanded, key_id tracked on Subprocess
  - _terminate: revoke_key called with correct key_id on eviction
  - No mutation of the input options dict
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_pool_manager.pool import Pool, Subprocess, _expand_mcp_placeholders
from agent_pool_manager.config import AgentPoolConfig


# ---------------------------------------------------------------------------
# _expand_mcp_placeholders unit tests
# ---------------------------------------------------------------------------

def test_expand_list_tether_placeholder():
    """['tether'] placeholder → full SSE config dict with Bearer header."""
    options = {"model": "haiku-4.5", "mcp_servers": ["tether"]}
    result = _expand_mcp_placeholders(options, mcp_key="test-key-abc")
    assert isinstance(result["mcp_servers"], dict)
    assert "tether" in result["mcp_servers"]
    tether_cfg = result["mcp_servers"]["tether"]
    assert tether_cfg["type"] == "sse"
    assert tether_cfg["url"] == "http://localhost:5001/sse"
    assert tether_cfg["headers"]["Authorization"] == "Bearer test-key-abc"


def test_expand_does_not_mutate_input():
    """_expand_mcp_placeholders must not mutate the original options dict."""
    options = {"mcp_servers": ["tether"]}
    original_mcp = options["mcp_servers"]
    _expand_mcp_placeholders(options, mcp_key="some-key")
    assert options["mcp_servers"] is original_mcp  # unchanged


def test_expand_passthrough_dict_form():
    """Already-expanded dict form is returned unchanged."""
    existing = {"tether": {"type": "sse", "url": "http://example.com/sse", "headers": {}}}
    options = {"mcp_servers": existing}
    result = _expand_mcp_placeholders(options, mcp_key="ignored")
    assert result["mcp_servers"] is existing


def test_expand_passthrough_none():
    """None mcp_servers stays None."""
    options = {"mcp_servers": None}
    result = _expand_mcp_placeholders(options, mcp_key="ignored")
    assert result["mcp_servers"] is None


def test_expand_passthrough_no_key():
    """Options without mcp_servers key are returned unchanged."""
    options = {"model": "haiku-4.5"}
    result = _expand_mcp_placeholders(options, mcp_key="ignored")
    assert "mcp_servers" not in result


def test_expand_list_without_tether_unchanged():
    """A list that doesn't contain 'tether' is passed through unchanged."""
    options = {"mcp_servers": ["other-server"]}
    result = _expand_mcp_placeholders(options, mcp_key="ignored")
    assert result["mcp_servers"] == ["other-server"]


# ---------------------------------------------------------------------------
# Spawn + key injection tests
# ---------------------------------------------------------------------------

def _make_pool(pg_pool=None) -> Pool:
    cfg = AgentPoolConfig(capacity_total=5, target_depth_per_hash=1)
    return Pool(cfg, pg_pool=pg_pool)


def _base_options() -> dict[str, Any]:
    return {
        "model": "haiku-4.5",
        "max_turns": 2,
        "permission_mode": "auto",
        "mcp_servers": ["tether"],
        "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"},
    }


@pytest.mark.asyncio
async def test_spawn_creates_mcp_key_and_expands_options():
    """When pg_pool + user_id provided, spawn calls create_key and passes expanded options."""
    fake_raw_key = "ttr_fakerawkey123"
    fake_key_record = {"id": "key-uuid-001", "name": "pool_mcp_abcdef01"}

    mock_pg_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pg_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pg_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    pool = _make_pool(pg_pool=mock_pg_pool)

    captured_sdk_options = []

    def fake_build_sdk_options(options, can_use_tool=None):
        captured_sdk_options.append(dict(options))
        sdk_opts = MagicMock()
        return sdk_opts

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    async def fake_do_prime(_client):
        pass

    with (
        patch(
            "db.pg_queries.api_keys.create_key",
            new=AsyncMock(return_value=(fake_raw_key, fake_key_record)),
        ) as mock_create_key,
        patch.object(Pool, "_build_sdk_options", side_effect=fake_build_sdk_options),
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
        patch.object(Pool, "_do_prime", new=staticmethod(fake_do_prime)),
    ):
        sub = await pool._spawn_and_prime(
            options_hash="abcdef01abcdef01",
            options=_base_options(),
            user_id="user-uuid-999",
        )

    # create_key was called with the right user_id
    mock_create_key.assert_awaited_once()
    call_args = mock_create_key.await_args
    assert call_args.kwargs.get("user_id") == "user-uuid-999" or call_args.args[1] == "user-uuid-999"

    # key_id is stored on the Subprocess
    assert sub.mcp_key_id == "key-uuid-001"

    # expanded options were passed to _build_sdk_options
    assert len(captured_sdk_options) == 1
    mcp = captured_sdk_options[0].get("mcp_servers")
    assert isinstance(mcp, dict), f"Expected dict mcp_servers, got {type(mcp)}: {mcp!r}"
    assert "tether" in mcp
    assert mcp["tether"]["headers"]["Authorization"] == f"Bearer {fake_raw_key}"


@pytest.mark.asyncio
async def test_spawn_without_pg_pool_skips_key_creation():
    """Without pg_pool, spawn proceeds without key creation (no mcp_key_id)."""
    pool = _make_pool(pg_pool=None)

    captured_sdk_options = []

    def fake_build_sdk_options(options, can_use_tool=None):
        captured_sdk_options.append(dict(options))
        return MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    async def fake_do_prime(_client):
        pass

    with (
        patch.object(Pool, "_build_sdk_options", side_effect=fake_build_sdk_options),
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
        patch.object(Pool, "_do_prime", new=staticmethod(fake_do_prime)),
    ):
        sub = await pool._spawn_and_prime(
            options_hash="abcdef01abcdef01",
            options=_base_options(),
            user_id="user-uuid-999",
        )

    # No key_id — skip gracefully
    assert sub.mcp_key_id is None

    # mcp_servers passed through unexpanded (list form)
    assert captured_sdk_options[0].get("mcp_servers") == ["tether"]


@pytest.mark.asyncio
async def test_spawn_without_user_id_skips_key_creation():
    """Without user_id, spawn proceeds even if pg_pool is available."""
    mock_pg_pool = MagicMock()
    pool = _make_pool(pg_pool=mock_pg_pool)

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    async def fake_do_prime(_client):
        pass

    with (
        patch.object(Pool, "_build_sdk_options", return_value=MagicMock()),
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
        patch.object(Pool, "_do_prime", new=staticmethod(fake_do_prime)),
        patch("db.pg_queries.api_keys.create_key") as mock_create_key,
    ):
        sub = await pool._spawn_and_prime(
            options_hash="abcdef01abcdef01",
            options=_base_options(),
            user_id=None,
        )

    mock_create_key.assert_not_called()
    assert sub.mcp_key_id is None


# ---------------------------------------------------------------------------
# Eviction / revoke tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_terminate_revokes_mcp_key():
    """_terminate calls revoke_key when sub has mcp_key_id."""
    mock_pg_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pg_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pg_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    pool = _make_pool(pg_pool=mock_pg_pool)

    mock_proc = MagicMock()
    mock_proc.disconnect = AsyncMock()

    sub = Subprocess(
        proc=mock_proc,
        options_hash="abcdef01abcdef01",
        options={},
        mcp_key_id="key-uuid-001",
        mcp_user_id="user-uuid-999",
    )

    with patch(
        "db.pg_queries.api_keys.revoke_key",
        new=AsyncMock(),
    ) as mock_revoke:
        await pool._terminate(sub)

    mock_revoke.assert_awaited_once()
    call_args = mock_revoke.await_args
    # revoke_key(conn, key_id, user_id) — check key_id and user_id
    assert "key-uuid-001" in call_args.args or call_args.kwargs.get("key_id") == "key-uuid-001"
    mock_proc.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminate_without_key_id_skips_revoke():
    """_terminate with no mcp_key_id does not attempt revoke."""
    mock_pg_pool = MagicMock()
    pool = _make_pool(pg_pool=mock_pg_pool)

    mock_proc = MagicMock()
    mock_proc.disconnect = AsyncMock()

    sub = Subprocess(
        proc=mock_proc,
        options_hash="abcdef01abcdef01",
        options={},
        mcp_key_id=None,
        mcp_user_id=None,
    )

    with patch("db.pg_queries.api_keys.revoke_key") as mock_revoke:
        await pool._terminate(sub)

    mock_revoke.assert_not_called()
    mock_proc.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminate_revoke_failure_does_not_block_disconnect():
    """Revoke failure must not prevent subprocess disconnect (fire-and-forget safety)."""
    mock_pg_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pg_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pg_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    pool = _make_pool(pg_pool=mock_pg_pool)

    mock_proc = MagicMock()
    mock_proc.disconnect = AsyncMock()

    sub = Subprocess(
        proc=mock_proc,
        options_hash="abcdef01abcdef01",
        options={},
        mcp_key_id="key-uuid-boom",
        mcp_user_id="user-uuid-999",
    )

    with patch(
        "db.pg_queries.api_keys.revoke_key",
        new=AsyncMock(side_effect=Exception("DB down")),
    ):
        # Must not raise
        await pool._terminate(sub)

    # Disconnect still runs despite revoke failure
    mock_proc.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminate_disconnect_before_revoke():
    """Disconnect must complete before revoke so in-flight MCP calls are not 401'd."""
    call_order: list[str] = []

    mock_pg_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pg_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pg_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    pool = _make_pool(pg_pool=mock_pg_pool)

    mock_proc = MagicMock()

    async def _disconnect():
        call_order.append("disconnect")
    mock_proc.disconnect = _disconnect

    sub = Subprocess(
        proc=mock_proc,
        options_hash="abcdef01abcdef01",
        options={},
        mcp_key_id="key-uuid-001",
        mcp_user_id="user-uuid-999",
    )

    async def _revoke(conn, key_id, user_id):
        call_order.append("revoke")
    with patch("db.pg_queries.api_keys.revoke_key", new=_revoke):
        await pool._terminate(sub)

    assert call_order == ["disconnect", "revoke"], (
        f"Expected disconnect before revoke, got: {call_order}"
    )


# ---------------------------------------------------------------------------
# Cross-user isolation tests (acquire-time user_id check)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acquire_skips_subprocess_with_wrong_user():
    """acquire() discards and terminates subprocesses belonging to a different user."""
    pool = _make_pool()

    mock_proc_wrong = MagicMock()
    mock_proc_wrong.disconnect = AsyncMock()
    mock_proc_right = MagicMock()
    mock_proc_right.disconnect = AsyncMock()

    # Push wrong-user subprocess first, right-user subprocess second
    sub_wrong = Subprocess(
        proc=mock_proc_wrong,
        options_hash="aabbccdd11223344",
        options={},
        mcp_key_id="key-wrong",
        mcp_user_id="user-A",
    )
    sub_right = Subprocess(
        proc=mock_proc_right,
        options_hash="aabbccdd11223344",
        options={},
        mcp_key_id="key-right",
        mcp_user_id="user-B",
    )

    queue = pool._get_or_create_queue("aabbccdd11223344")
    await queue.put(sub_wrong)
    await queue.put(sub_right)

    handle_id, _ = await pool.acquire(
        options_hash="aabbccdd11223344",
        options={},
        user_id="user-B",
    )

    # The right subprocess was handed out
    async with pool._lock:
        active_sub = pool._active[handle_id]
    assert active_sub.mcp_user_id == "user-B"

    # The wrong subprocess was terminated
    # (give the task a chance to run)
    await asyncio.sleep(0)
    mock_proc_wrong.disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# Key revocation on spawn failure tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_failure_revokes_key():
    """If connect() fails after key creation, the ephemeral key is revoked."""
    fake_raw_key = "ttr_fakerawkey123"
    fake_key_record = {"id": "key-uuid-leak", "name": "pool_mcp_abcdef01"}

    mock_pg_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pg_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pg_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    pool = _make_pool(pg_pool=mock_pg_pool)

    mock_client = MagicMock()
    mock_client.connect = AsyncMock(side_effect=Exception("connect failed"))

    with (
        patch(
            "db.pg_queries.api_keys.create_key",
            new=AsyncMock(return_value=(fake_raw_key, fake_key_record)),
        ),
        patch(
            "db.pg_queries.api_keys.revoke_key",
            new=AsyncMock(),
        ) as mock_revoke,
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
    ):
        with pytest.raises(Exception, match="connect failed"):
            await pool._spawn_and_prime(
                options_hash="abcdef01abcdef01",
                options=_base_options(),
                user_id="user-uuid-999",
            )

    mock_revoke.assert_awaited_once()
    args = mock_revoke.await_args.args
    assert "key-uuid-leak" in args


# ---------------------------------------------------------------------------
# Bug 1: empty-string user_id must be treated same as None (no key creation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_with_empty_string_user_id_skips_key_creation():
    """user_id='' must not trigger create_key — would cause UUID parse error in DB."""
    mock_pg_pool = MagicMock()
    pool = _make_pool(pg_pool=mock_pg_pool)

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    async def fake_do_prime(_client):
        pass

    with (
        patch.object(Pool, "_build_sdk_options", return_value=MagicMock()),
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
        patch.object(Pool, "_do_prime", new=staticmethod(fake_do_prime)),
        patch("db.pg_queries.api_keys.create_key") as mock_create_key,
    ):
        sub = await pool._spawn_and_prime(
            options_hash="abcdef01abcdef01",
            options=_base_options(),
            user_id="",  # empty string — must be treated as absent
        )

    mock_create_key.assert_not_called()
    assert sub.mcp_key_id is None


# ---------------------------------------------------------------------------
# Bug 2: key creation failure must strip ['tether'] placeholder before spawn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_key_failure_strips_mcp_placeholder():
    """When key creation fails, mcp_servers must be replaced with {} so SDK doesn't hang."""
    mock_pg_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pg_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pg_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    pool = _make_pool(pg_pool=mock_pg_pool)
    captured_sdk_options: list[dict] = []

    def fake_build_sdk_options(options, can_use_tool=None):
        captured_sdk_options.append(dict(options))
        return MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()

    async def fake_do_prime(_client):
        pass

    with (
        patch(
            "db.pg_queries.api_keys.create_key",
            new=AsyncMock(side_effect=Exception("DB error")),
        ),
        patch.object(Pool, "_build_sdk_options", side_effect=fake_build_sdk_options),
        patch("agent_pool_manager.pool.ClaudeSDKClient", return_value=mock_client),
        patch.object(Pool, "_do_prime", new=staticmethod(fake_do_prime)),
    ):
        sub = await pool._spawn_and_prime(
            options_hash="abcdef01abcdef01",
            options=_base_options(),
            user_id="user-uuid-999",
        )

    assert len(captured_sdk_options) == 1
    mcp = captured_sdk_options[0].get("mcp_servers")
    # Must NOT be the list placeholder — that would cause SDK to hang
    assert not isinstance(mcp, list), (
        f"mcp_servers must not be a list after key creation failure, got: {mcp!r}"
    )
    # Must be an empty dict (no MCP servers) so subprocess can start without MCP auth
    assert mcp == {}, f"Expected empty dict mcp_servers on fallback, got: {mcp!r}"
