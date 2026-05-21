"""Tests for A6 control-protocol wire-up in interactive_agent_layer.session.

Covers:
- control_request for background tool → auto-allow → send_control_response("allow")
- control_request for user_action tool with auto_approve=True → allow
- control_request for user_action tool → permission_request WS event + user approves → allow
- control_request for user_action tool → user denies → deny
- control_timeout event is silently skipped (pool already denied, no send_control_response)
- stale-request 404 on send_control_response is swallowed, turn completes normally
- Round-trip integration: real PoolClient ↔ FastAPI ↔ ControlBridge in-process
"""
from __future__ import annotations

import asyncio
import pathlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

import pytest

from interactive_agent_layer.permissions import PermissionResultAllow, PermissionResultDeny
from interactive_agent_layer.session import Layer, Session
from interactive_agent_layer.ws_publisher import WSPublisher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_permission_timeout(monkeypatch):
    """Avoid loading the real config (needs jwt.secret) when PermissionGate runs."""
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 30,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_YAML_PATH = (
    pathlib.Path(__file__).parent.parent.parent / "config" / "agent_translations.yaml"
)


def _make_layer(
    pool_client,
    ws_publisher: WSPublisher | None = None,
) -> Layer:
    """Build a Layer with TranslationTable loaded from config.

    get_auto_approve_user_actions is patched globally to False by the conftest
    autouse fixture.  Tests that need auto_approve=True must patch it themselves
    around the run_turn call.
    """
    from interactive_agent_layer.translation import TranslationTable

    if ws_publisher is None:
        ws_publisher = WSPublisher()

    return Layer(
        pool_client=pool_client,
        ws_publisher=ws_publisher,
        translation_table=TranslationTable.from_yaml(_YAML_PATH),
    )


class _BasePool:
    """Base class for test pool clients."""

    _send_control_calls: list[dict]

    def __init__(self):
        self._send_control_calls = []

    async def acquire(
        self, user_id: str, options_hash: str, options: dict, timeout_seconds=None
    ) -> str:
        return "test-handle"

    async def release(self, handle_id: str, *, reusable: bool = False) -> None:
        pass

    async def interrupt(self, handle_id: str) -> None:
        pass

    async def send_control_response(
        self,
        handle_id: str,
        *,
        request_id: str,
        subtype: str,
        decision: str,
        denial_message: str | None = None,
    ) -> None:
        self._send_control_calls.append(
            {
                "handle_id": handle_id,
                "request_id": request_id,
                "subtype": subtype,
                "decision": decision,
                "denial_message": denial_message,
            }
        )


# ---------------------------------------------------------------------------
# Test 1: background tool → auto-allow
# ---------------------------------------------------------------------------

async def test_control_request_background_tool_auto_allows():
    """control_request for get_anchors (background) → send_control_response("allow")."""

    class _Pool(_BasePool):
        async def query_stream(self, handle_id, prompt, session_id="default"):
            yield {
                "event": "control_request",
                "request_id": "req-bg-001",
                "subtype": "can_use_tool",
                "tool_name": "get_anchors",
                "tool_input": {},
            }
            yield {"type": "result", "final_text": "done", "tokens_used": 1}

    pool = _Pool()
    layer = _make_layer(pool)

    s = layer.create_session("user1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    assert len(pool._send_control_calls) == 1
    call = pool._send_control_calls[0]
    assert call["handle_id"] == "test-handle"
    assert call["request_id"] == "req-bg-001"
    assert call["subtype"] == "can_use_tool"
    assert call["decision"] == "allow"

    # control_request should NOT produce a layer event
    types = [e["type"] for e in events]
    assert "turn_complete" in types
    assert "permission_request" not in types


# ---------------------------------------------------------------------------
# Test 2: user_action tool + auto_approve=True → allow without WS prompt
# ---------------------------------------------------------------------------

async def test_control_request_user_action_auto_approve_allows():
    """user_action tool with auto_approve=True → allow, no permission_request WS event."""

    published: list[dict] = []

    class _Pool(_BasePool):
        async def query_stream(self, handle_id, prompt, session_id="default"):
            yield {
                "event": "control_request",
                "request_id": "req-ua-auto",
                "subtype": "can_use_tool",
                "tool_name": "upsert_tasks",
                "tool_input": {"tasks": [], "count": 0},
            }
            yield {"type": "result", "final_text": "done", "tokens_used": 1}

    pool = _Pool()
    ws = WSPublisher()
    ws.push = AsyncMock(side_effect=lambda ws_id, event: published.append(event))
    layer = _make_layer(pool, ws)

    s = layer.create_session("user1", "ws1", "v1", {})

    # Override the conftest autouse patch: auto_approve=True for this turn
    with patch(
        "interactive_agent_layer.session.get_auto_approve_user_actions",
        return_value=True,
    ):
        await _consume(layer.run_turn(s.session_id, "hi"))

    assert len(pool._send_control_calls) == 1
    assert pool._send_control_calls[0]["decision"] == "allow"
    perm_events = [e for e in published if e.get("type") == "permission_request"]
    assert perm_events == [], "auto_approve must not emit permission_request"


# ---------------------------------------------------------------------------
# Test 3: user_action tool, user approves → allow + permission_request WS event
# ---------------------------------------------------------------------------

async def test_control_request_user_action_user_approves():
    """user_action tool: permission_request WS event emitted, user approves → allow."""

    published: list[dict] = []
    session_holder: list[Session] = []

    class _Pool(_BasePool):
        async def query_stream(self, handle_id, prompt, session_id="default"):
            yield {
                "event": "control_request",
                "request_id": "req-ua-approve",
                "subtype": "can_use_tool",
                "tool_name": "upsert_tasks",
                "tool_input": {"tasks": ["buy milk"], "count": 1},
            }
            yield {"type": "result", "final_text": "done", "tokens_used": 1}

    async def _ws_push(ws_id: str, event: dict) -> None:
        published.append(event)
        if event.get("type") == "permission_request":
            # Simulate user approving immediately
            request_id = event["request_id"]
            sess = session_holder[0]
            fut = sess.permission_pending.get(request_id)
            if fut is not None and not fut.done():
                fut.set_result(True)

    pool = _Pool()
    ws = WSPublisher()
    ws.push = _ws_push
    layer = _make_layer(pool, ws)

    s = layer.create_session("user1", "ws1", "v1", {})
    session_holder.append(s)

    await _consume(layer.run_turn(s.session_id, "hi"))

    perm_events = [e for e in published if e.get("type") == "permission_request"]
    assert len(perm_events) == 1
    assert perm_events[0]["summary"] == "Update 1 tasks"

    assert len(pool._send_control_calls) == 1
    assert pool._send_control_calls[0]["decision"] == "allow"


# ---------------------------------------------------------------------------
# Test 4: user_action tool, user denies → deny
# ---------------------------------------------------------------------------

async def test_control_request_user_action_user_denies():
    """user_action tool: user denies → send_control_response("deny")."""

    session_holder: list[Session] = []

    class _Pool(_BasePool):
        async def query_stream(self, handle_id, prompt, session_id="default"):
            yield {
                "event": "control_request",
                "request_id": "req-ua-deny",
                "subtype": "can_use_tool",
                "tool_name": "upsert_tasks",
                "tool_input": {"tasks": [], "count": 0},
            }
            yield {"type": "result", "final_text": "done", "tokens_used": 1}

    async def _ws_push(ws_id: str, event: dict) -> None:
        if event.get("type") == "permission_request":
            request_id = event["request_id"]
            sess = session_holder[0]
            fut = sess.permission_pending.get(request_id)
            if fut is not None and not fut.done():
                fut.set_result(False)

    pool = _Pool()
    ws = WSPublisher()
    ws.push = _ws_push
    layer = _make_layer(pool, ws)

    s = layer.create_session("user1", "ws1", "v1", {})
    session_holder.append(s)

    await _consume(layer.run_turn(s.session_id, "hi"))

    assert len(pool._send_control_calls) == 1
    assert pool._send_control_calls[0]["decision"] == "deny"


# ---------------------------------------------------------------------------
# Test 5: control_timeout is silently skipped
# ---------------------------------------------------------------------------

async def test_control_timeout_is_silently_skipped():
    """control_timeout SSE event is ignored — no send_control_response, turn completes."""

    class _Pool(_BasePool):
        async def query_stream(self, handle_id, prompt, session_id="default"):
            yield {"event": "control_timeout", "request_id": "req-timeout-001"}
            yield {"type": "result", "final_text": "done", "tokens_used": 1}

    pool = _Pool()
    layer = _make_layer(pool)

    s = layer.create_session("user1", "ws1", "v1", {})
    events = await _consume_list(layer.run_turn(s.session_id, "hi"))

    assert pool._send_control_calls == []
    types = [e["type"] for e in events]
    assert "turn_complete" in types


# ---------------------------------------------------------------------------
# Test 6: stale 404 on send_control_response is swallowed
# ---------------------------------------------------------------------------

async def test_control_request_stale_404_is_swallowed():
    """If pool times out before layer responds, send_control_response raises PoolClientError.
    The layer must swallow it and complete the turn normally."""
    from agent_pool_manager.client import PoolClientError

    class _Pool(_BasePool):
        async def query_stream(self, handle_id, prompt, session_id="default"):
            yield {
                "event": "control_request",
                "request_id": "req-stale",
                "subtype": "can_use_tool",
                "tool_name": "get_anchors",
                "tool_input": {},
            }
            yield {"type": "result", "final_text": "done", "tokens_used": 1}

        async def send_control_response(self, handle_id, *, request_id, subtype, decision, denial_message=None):
            raise PoolClientError("HTTP 404: request_id 'req-stale' not found or already resolved")

    pool = _Pool()
    layer = _make_layer(pool)

    s = layer.create_session("user1", "ws1", "v1", {})
    # Must not raise — stale 404 should be logged and swallowed
    events = await _consume_list(layer.run_turn(s.session_id, "hi"))
    types = [e["type"] for e in events]
    assert "turn_complete" in types


# ---------------------------------------------------------------------------
# Test 7: multiple control_requests in one turn
# ---------------------------------------------------------------------------

async def test_multiple_control_requests_in_one_turn():
    """Two control_request events in sequence both get responses."""

    class _Pool(_BasePool):
        async def query_stream(self, handle_id, prompt, session_id="default"):
            yield {
                "event": "control_request",
                "request_id": "req-001",
                "subtype": "can_use_tool",
                "tool_name": "get_anchors",
                "tool_input": {},
            }
            yield {
                "event": "control_request",
                "request_id": "req-002",
                "subtype": "can_use_tool",
                "tool_name": "get_context",
                "tool_input": {},
            }
            yield {"type": "result", "final_text": "done", "tokens_used": 1}

    pool = _Pool()
    layer = _make_layer(pool)

    s = layer.create_session("user1", "ws1", "v1", {})
    await _consume(layer.run_turn(s.session_id, "hi"))

    assert len(pool._send_control_calls) == 2
    request_ids = {c["request_id"] for c in pool._send_control_calls}
    assert request_ids == {"req-001", "req-002"}
    for call in pool._send_control_calls:
        assert call["decision"] == "allow"


# ---------------------------------------------------------------------------
# Integration test: real PoolClient ↔ FastAPI ↔ real ControlBridge in-process
# ---------------------------------------------------------------------------

async def test_integration_control_protocol_round_trip():
    """Real PoolClient → FastAPI pool service → ControlBridge → control_response.

    Uses a fake Pool that injects a can_use_tool callback mid-query via
    ControlBridge.request().  No real Claude subprocess needed.

    Architecture note on ASGITransport:
    httpx's ASGITransport buffers the entire streaming response before
    delivering any chunks to the caller.  This means the SSE stream (running
    inside ``await app(scope, receive, send)``) must complete before
    ``query_stream`` can yield any events.  Consequently a second HTTP call
    (``send_control_response``) cannot complete while the SSE stream is
    running — doing so would deadlock.

    Workaround: we resolve the bridge future directly (``bridge.respond``) from
    the main task while the stream is blocked, allowing the ASGI app to
    complete.  The layer still processes the buffered ``control_request`` event
    and calls ``send_control_response``, which gets a 404 (bridge already
    resolved) — the layer's stale-request handling is tested by
    ``test_control_request_stale_404_is_swallowed``.

    This test verifies:
    - Pool emits ``control_request`` SSE event with correct shape
    - Bridge future resolves with the expected decision
    - Turn completes normally (``turn_complete`` event produced)
    - ``send_control_response`` 404 is silently swallowed (no exception)
    """
    from agent_pool_manager.client import PoolClient
    from agent_pool_manager.control import ControlBridge
    from agent_pool_manager.server import build_app

    bridge = ControlBridge(timeout_seconds=5.0)
    handle_id = "int-handle-001"
    tool_decision: list[str] = []

    # ------------------------------------------------------------------
    # Fake subprocess: receive_response triggers a bridge permission request
    # mid-stream then yields a result message.
    # ------------------------------------------------------------------
    class _FakeSubproc:
        async def query(self, prompt: str, session_id: str = "default") -> None:
            pass

        async def receive_response(self) -> AsyncIterator[Any]:
            resp = await bridge.request(
                handle_id,
                "can_use_tool",
                {"tool_name": "get_anchors", "tool_input": {}},
            )
            tool_decision.append(resp.get("decision", "unknown"))
            # Use a dict-backed object so _serialise_msg(msg) returns
            # {"type": "result", ...} — vars() returns {} for class-attr objects.
            result_obj = SimpleNamespace(type="result", final_text="ok", tokens_used=1)
            yield result_obj

    fake_subproc = _FakeSubproc()
    _SubHolder = type("Sub", (), {"proc": fake_subproc})

    # ------------------------------------------------------------------
    # Fake Pool with the minimal surface server.py accesses.
    # ------------------------------------------------------------------
    class _FakePool:
        def __init__(self):
            self._lock = asyncio.Lock()
            self._active: dict = {handle_id: _SubHolder()}
            self.control_bridge = bridge

        async def acquire(self, *a, **kw):
            return handle_id, {"ready_at": "2026-01-01T00:00:00Z"}

        async def release(self, *a, **kw):
            pass

        async def interrupt(self, *a, **kw):
            pass

        def status(self):
            return {}

    fake_pool = _FakePool()

    # set app.state directly — lifespan does not fire with ASGITransport
    app = build_app()
    app.state.pool = fake_pool
    app.state.refill = MagicMock()

    transport = ASGITransport(app=app)
    pool_client = PoolClient(base_url="http://test", _transport=transport)
    ws_publisher = WSPublisher()
    layer = _make_layer(pool_client, ws_publisher)

    s = layer.create_session("user1", "ws1", "v1", {})
    events: list[dict] = []

    async def _run_turn():
        async for e in layer.run_turn(s.session_id, "hi"):
            events.append(e)

    # Run the turn as a background task so we can concurrently inject
    # the bridge response from this task.
    turn_task = asyncio.create_task(_run_turn())

    # Yield repeatedly until the bridge has a pending request (meaning
    # _run_sdk is blocked inside bridge.request waiting for a decision).
    for _ in range(200):  # up to 2 seconds in 10ms steps
        await asyncio.sleep(0.01)
        if bridge._pending:
            break

    assert bridge._pending, "bridge._pending must have an entry (bridge.request was called)"

    # Resolve the bridge future directly: get_anchors is a background tool → allow.
    request_id = next(iter(bridge._pending))
    resolved = bridge.respond(request_id, {"decision": "allow"})
    assert resolved, "bridge.respond must return True"

    # Wait for the turn to complete (stream completes, layer processes events)
    await asyncio.wait_for(turn_task, timeout=5.0)

    # Bridge callback returned "allow"
    assert tool_decision == ["allow"], f"Expected ['allow'], got {tool_decision}"

    # Turn produced a turn_complete event
    types = [e["type"] for e in events]
    assert "turn_complete" in types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _consume(ait) -> None:
    async for _ in ait:
        pass


async def _consume_list(ait) -> list[dict]:
    events = []
    async for e in ait:
        events.append(e)
    return events
