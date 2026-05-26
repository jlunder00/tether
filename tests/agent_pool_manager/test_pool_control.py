"""Tests for pool.py control-protocol integration — forwarding callback wired at spawn."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from .fake_client import FakeClient
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool


HASH_A = "abc123"
OPTIONS_A = {"model": "claude-haiku-4-5-20251001", "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"}}


@pytest.fixture
def pool() -> Pool:
    cfg = AgentPoolConfig(
        target_depth_per_hash=1,
        capacity_total=4,
        max_age_seconds=600,
        control_response_timeout_seconds=0.2,
    )
    return Pool(cfg)


@pytest.fixture
def capturing_client():
    """Patches ClaudeSDKClient with a FakeClient subclass that records constructor options.

    Yields the list of captured ``options`` (one entry per spawn) so tests can
    reach the wired ``can_use_tool`` callback.
    """
    constructed_options: list = []

    class CapturingFakeClient(FakeClient):
        def __init__(self, options=None, **kw):
            super().__init__(options=options, **kw)
            constructed_options.append(options)

    with patch("agent_pool_manager.pool.ClaudeSDKClient", CapturingFakeClient):
        yield constructed_options


# ---------------------------------------------------------------------------
# Callback wired at spawn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawned_client_receives_can_use_tool_callback(pool: Pool, capturing_client):
    """ClaudeSDKClient is constructed with a can_use_tool callback when spawned."""
    await pool._inject_warm(HASH_A, OPTIONS_A)

    assert len(capturing_client) == 1
    sdk_opts = capturing_client[0]
    assert sdk_opts is not None
    assert callable(sdk_opts.can_use_tool)


@pytest.mark.asyncio
async def test_can_use_tool_callback_fires_control_request(pool: Pool, capturing_client):
    """When the callback fires it registers a pending request in the ControlBridge."""
    await pool._inject_warm(HASH_A, OPTIONS_A)

    await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0)
    callback = capturing_client[0].can_use_tool

    # Fire the callback in background, immediately respond via bridge
    bridge = pool.control_bridge
    fired = asyncio.create_task(callback("bash", {}, MagicMock()))
    await asyncio.sleep(0)

    request_ids = list(bridge._pending.keys())
    assert len(request_ids) == 1
    bridge.respond(request_ids[0], {"decision": "allow"})

    result = await fired
    assert isinstance(result, PermissionResultAllow)


@pytest.mark.asyncio
async def test_can_use_tool_callback_deny_returns_permission_deny(pool: Pool, capturing_client):
    """Callback returns PermissionResultDeny when bridge responds deny."""
    await pool._inject_warm(HASH_A, OPTIONS_A)

    await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0)
    callback = capturing_client[0].can_use_tool
    bridge = pool.control_bridge

    fired = asyncio.create_task(callback("bash", {}, MagicMock()))
    await asyncio.sleep(0)
    request_ids = list(bridge._pending.keys())
    bridge.respond(request_ids[0], {"decision": "deny", "denial_message": "not allowed"})

    result = await fired
    assert isinstance(result, PermissionResultDeny)
    assert result.message == "not allowed"


@pytest.mark.asyncio
async def test_can_use_tool_callback_timeout_returns_deny(pool: Pool, capturing_client):
    """Callback returns PermissionResultDeny on timeout (fail-closed)."""
    await pool._inject_warm(HASH_A, OPTIONS_A)

    await pool.acquire(HASH_A, OPTIONS_A, timeout=1.0)
    callback = capturing_client[0].can_use_tool

    result = await callback("bash", {}, MagicMock())
    assert isinstance(result, PermissionResultDeny)
