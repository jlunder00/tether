"""Tests for server.py control-protocol extension — SSE events + /control_response."""
from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import patch
from httpx import ASGITransport

from .fake_client import FakeClient
from agent_pool_manager.config import AgentPoolConfig
from agent_pool_manager.pool import Pool
from agent_pool_manager.refill import RefillLoop
from agent_pool_manager.server import build_app
from agent_pool_manager.client import PoolClient, PoolClientError


HASH_A = "abc123"
OPTIONS_A = {"model": "claude-haiku-4-5-20251001", "env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token"}}
USER_ID = "user-ctrl-1"


@pytest.fixture
async def pool_and_app():
    cfg = AgentPoolConfig(
        target_depth_per_hash=2,
        capacity_total=8,
        max_age_seconds=600,
        refill_poll_interval=0.05,
        prime_timeout_seconds=5,
        acquire_default_timeout=2,
        control_response_timeout_seconds=0.3,
    )
    pool = Pool(cfg)
    refill = RefillLoop(pool)
    app = build_app(pool=pool, refill=refill)
    app.state.pool = pool
    app.state.refill = refill
    refill.start()
    yield pool, app
    refill.stop()


@pytest.fixture
async def http_client(pool_and_app):
    pool, app = pool_and_app
    transport = ASGITransport(app=app)
    client = PoolClient(base_url="http://test", _transport=transport)
    try:
        yield client, pool
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# POST /handle/{id}/control_response — basic routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_control_response_unknown_request_returns_404(http_client):
    """POST /control_response with an unknown request_id raises PoolClientError 404."""
    client, pool = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id = await client.acquire(USER_ID, HASH_A, OPTIONS_A, timeout_seconds=2.0)
    with pytest.raises(PoolClientError, match="404"):
        await client.send_control_response(
            handle_id,
            request_id="no-such-id",
            subtype="can_use_tool",
            decision="allow",
        )
    await client.release(handle_id)


@pytest.mark.asyncio
async def test_control_response_resolves_pending_bridge_request(http_client):
    """POST /control_response resolves a pending ControlBridge future."""
    client, pool = http_client
    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClient):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id = await client.acquire(USER_ID, HASH_A, OPTIONS_A, timeout_seconds=2.0)
    bridge = pool.control_bridge

    # Register a pending request directly in the bridge
    req_task = asyncio.create_task(
        bridge.request(handle_id, "can_use_tool", {"tool_name": "bash", "tool_input": {}})
    )
    await asyncio.sleep(0)
    request_id = list(bridge._pending.keys())[0]

    # Resolve it via the HTTP endpoint
    await client.send_control_response(
        handle_id,
        request_id=request_id,
        subtype="can_use_tool",
        decision="allow",
    )

    result = await req_task
    assert result["decision"] == "allow"
    await client.release(handle_id)


# ---------------------------------------------------------------------------
# SSE stream emits control_request events
# ---------------------------------------------------------------------------

class FakeClientWithControlRequest(FakeClient):
    """FakeClient whose can_use_tool callback fires (and blocks) during receive_response.

    Simulates real SDK behaviour: can_use_tool fires mid-stream and
    receive_response() cannot yield further messages until it resolves.
    """

    def __init__(self, options=None, **kw):
        super().__init__(options=options, **kw)
        self._can_use_tool_cb = options.can_use_tool if options else None

    async def receive_response(self):
        # Fire the callback and wait for it — blocks until the caller responds.
        if self._can_use_tool_cb is not None:
            from unittest.mock import MagicMock
            await self._can_use_tool_cb("bash", {"cmd": "ls"}, MagicMock())
        async for msg in super().receive_response():
            yield msg


@pytest.mark.asyncio
async def test_query_stream_emits_control_request_event(http_client):
    """query_stream() yields a control_request event when the callback fires."""
    client, pool = http_client

    with patch("agent_pool_manager.pool.ClaudeSDKClient", FakeClientWithControlRequest):
        await pool._inject_warm(HASH_A, OPTIONS_A)

    handle_id = await client.acquire(USER_ID, HASH_A, OPTIONS_A, timeout_seconds=2.0)

    control_events = []
    other_events = []

    async def _consume():
        async for event in client.query_stream(handle_id, "do something"):
            if event.get("event") == "control_request":
                control_events.append(event)
                # Respond so the stream can complete
                bridge = pool.control_bridge
                rid = event["request_id"]
                bridge.respond(rid, {"decision": "allow"})
            else:
                other_events.append(event)

    await asyncio.wait_for(_consume(), timeout=5.0)

    assert len(control_events) >= 1
    evt = control_events[0]
    assert evt["subtype"] == "can_use_tool"
    assert "request_id" in evt
    assert evt["tool_name"] == "bash"
    await client.release(handle_id)
