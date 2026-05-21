"""Tests for agent_pool_manager.control — ControlBridge futures management."""
from __future__ import annotations

import asyncio
import pytest

from agent_pool_manager.control import ControlBridge, ControlTimeout


HANDLE_A = "handle-aaa"
HANDLE_B = "handle-bbb"


@pytest.fixture
def bridge() -> ControlBridge:
    return ControlBridge(timeout_seconds=0.2)


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_respond_resolves_pending_request(bridge: ControlBridge):
    """respond() resolves the future returned by request()."""
    req_task = asyncio.create_task(
        bridge.request(HANDLE_A, "can_use_tool", {"tool_name": "bash", "tool_input": {}})
    )
    # yield so the task registers the future
    await asyncio.sleep(0)

    request_id = list(bridge._pending.keys())[0]
    bridge.respond(request_id, {"decision": "allow"})

    result = await req_task
    assert result == {"decision": "allow"}


@pytest.mark.asyncio
async def test_respond_returns_true_for_known_request(bridge: ControlBridge):
    """respond() returns True when the request_id is known."""
    req_task = asyncio.create_task(
        bridge.request(HANDLE_A, "can_use_tool", {"tool_name": "bash", "tool_input": {}})
    )
    await asyncio.sleep(0)

    request_id = list(bridge._pending.keys())[0]
    result = bridge.respond(request_id, {"decision": "allow"})
    assert result is True
    await req_task


@pytest.mark.asyncio
async def test_respond_returns_false_for_unknown_request(bridge: ControlBridge):
    """respond() returns False for an unknown or already-resolved request_id."""
    result = bridge.respond("no-such-id", {"decision": "allow"})
    assert result is False


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_raises_control_timeout(bridge: ControlBridge):
    """request() raises ControlTimeout after timeout_seconds with no response."""
    with pytest.raises(ControlTimeout):
        await bridge.request(HANDLE_A, "can_use_tool", {"tool_name": "bash", "tool_input": {}})


@pytest.mark.asyncio
async def test_timed_out_request_removed_from_pending(bridge: ControlBridge):
    """A timed-out request is cleaned up from _pending."""
    with pytest.raises(ControlTimeout):
        await bridge.request(HANDLE_A, "can_use_tool", {"tool_name": "bash", "tool_input": {}})
    assert len(bridge._pending) == 0


# ---------------------------------------------------------------------------
# Concurrent requests on same handle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_requests_on_same_handle(bridge: ControlBridge):
    """Multiple concurrent requests on the same handle are tracked independently."""
    bridge2 = ControlBridge(timeout_seconds=1.0)

    t1 = asyncio.create_task(
        bridge2.request(HANDLE_A, "can_use_tool", {"tool_name": "bash", "tool_input": {}})
    )
    t2 = asyncio.create_task(
        bridge2.request(HANDLE_A, "can_use_tool", {"tool_name": "read_file", "tool_input": {}})
    )
    await asyncio.sleep(0)

    ids = list(bridge2._pending.keys())
    assert len(ids) == 2

    bridge2.respond(ids[0], {"decision": "allow"})
    bridge2.respond(ids[1], {"decision": "deny"})

    r1, r2 = await asyncio.gather(t1, t2)
    decisions = {r1["decision"], r2["decision"]}
    assert decisions == {"allow", "deny"}


# ---------------------------------------------------------------------------
# Handle queue registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_handle_receives_sse_event():
    """register_handle() returns a queue that receives control_request events."""
    b = ControlBridge(timeout_seconds=1.0)
    q = b.register_handle(HANDLE_A)

    req_task = asyncio.create_task(
        b.request(HANDLE_A, "can_use_tool", {"tool_name": "bash", "tool_input": {}})
    )
    await asyncio.sleep(0)

    # Queue should have the SSE event now
    assert not q.empty()
    evt = q.get_nowait()
    assert evt["event"] == "control_request"
    assert evt["subtype"] == "can_use_tool"
    assert evt["tool_name"] == "bash"
    assert "request_id" in evt

    b.respond(evt["request_id"], {"decision": "allow"})
    await req_task


@pytest.mark.asyncio
async def test_deregister_handle_stops_event_delivery():
    """deregister_handle() removes the queue so future requests don't enqueue."""
    b = ControlBridge(timeout_seconds=1.0)
    q = b.register_handle(HANDLE_A)
    b.deregister_handle(HANDLE_A)

    req_task = asyncio.create_task(
        b.request(HANDLE_A, "can_use_tool", {"tool_name": "bash", "tool_input": {}})
    )
    await asyncio.sleep(0)
    assert q.empty()

    request_id = list(b._pending.keys())[0]
    b.respond(request_id, {"decision": "allow"})
    await req_task


# ---------------------------------------------------------------------------
# request_id uniqueness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_each_request_gets_unique_id(bridge: ControlBridge):
    """Each call to request() registers a distinct request_id."""
    bridge2 = ControlBridge(timeout_seconds=1.0)
    t1 = asyncio.create_task(
        bridge2.request(HANDLE_A, "can_use_tool", {"tool_name": "a", "tool_input": {}})
    )
    t2 = asyncio.create_task(
        bridge2.request(HANDLE_B, "can_use_tool", {"tool_name": "b", "tool_input": {}})
    )
    await asyncio.sleep(0)

    ids = list(bridge2._pending.keys())
    assert ids[0] != ids[1]

    for rid in ids:
        bridge2.respond(rid, {"decision": "allow"})
    await asyncio.gather(t1, t2)
