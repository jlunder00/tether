"""Tests for Session dataclass and Layer class."""
from __future__ import annotations

import pathlib

import pytest

from interactive_agent_layer.session import Layer, Session
from interactive_agent_layer.ws_publisher import WSPublisher


# ---------------------------------------------------------------------------
# Local mocks for pool integration + interrupt tests
# These classes match the REAL PoolClient API (str options_hash, options dict,
# query_stream instead of query, release keyword-only reusable).
# ---------------------------------------------------------------------------

class _RealApiMockPool:
    """Mock matching the real agent_pool_manager.client.PoolClient API."""

    async def acquire(
        self, user_id: str, options_hash: str, options: dict, timeout_seconds=None
    ) -> str:
        return f"mock-handle-{user_id}"

    async def query_stream(self, handle_id: str, prompt: str, session_id: str = "default"):
        yield {"type": "text_delta", "delta": "Hello "}
        yield {"type": "tool_use", "tool_name": "get_anchors", "args": {}}
        yield {"type": "tool_use", "tool_name": "send_status_update", "args": {"text": "Still working"}}
        yield {"type": "text_delta", "delta": "world"}
        yield {"type": "result", "final_text": "Hello world", "tokens_used": 42}

    async def release(self, handle_id: str, *, reusable: bool = False) -> None:
        pass

    async def interrupt(self, handle_id: str) -> None:
        pass


class _CancellingMockPool:
    """Pool client that yields a cancelled event — simulates a mid-turn interrupt."""

    async def acquire(
        self, user_id: str, options_hash: str, options: dict, timeout_seconds=None
    ) -> str:
        return f"handle-{user_id}"

    async def query_stream(self, handle_id: str, prompt: str, session_id: str = "default"):
        yield {"type": "text_delta", "delta": "Starting..."}
        yield {"event": "cancelled"}

    async def release(self, handle_id: str, *, reusable: bool = False) -> None:
        pass

    async def interrupt(self, handle_id: str) -> None:
        pass


class _TrackingMockPool:
    """Pool client that records whether interrupt was called."""

    def __init__(self):
        self.interrupted_handles: list[str] = []

    async def acquire(
        self, user_id: str, options_hash: str, options: dict, timeout_seconds=None
    ) -> str:
        return f"handle-{user_id}"

    async def query_stream(self, handle_id: str, prompt: str, session_id: str = "default"):
        yield {"type": "result", "final_text": "done", "tokens_used": 1}

    async def release(self, handle_id: str, *, reusable: bool = False) -> None:
        pass

    async def interrupt(self, handle_id: str) -> None:
        self.interrupted_handles.append(handle_id)


def _make_layer(pool_client) -> Layer:
    yaml_path = (
        pathlib.Path(__file__).parent.parent.parent / "config" / "agent_translations.yaml"
    )
    from interactive_agent_layer.translation import TranslationTable
    return Layer(
        pool_client=pool_client,
        ws_publisher=WSPublisher(),
        translation_table=TranslationTable.from_yaml(yaml_path),
    )


def test_session_dataclass_fields():
    s = Session(
        session_id="abc",
        user_id="user1",
        user_ws_id="wsid1",
        agent_version="v1",
        options={"key": "val"},
    )
    assert s.session_id == "abc"
    assert s.user_id == "user1"
    assert s.user_ws_id == "wsid1"
    assert s.agent_version == "v1"
    assert s.options == {"key": "val"}
    assert s.active_handles == []
    assert s.turn_count == 0
    assert s.created_at > 0


def test_layer_create_session(layer):
    s = layer.create_session(
        user_id="user1",
        user_ws_id="wsid1",
        agent_version="v1",
        options={},
    )
    assert s.session_id in layer.sessions
    assert layer.sessions[s.session_id] is s
    assert s.user_id == "user1"


def test_layer_get_session(layer):
    s = layer.create_session("user1", "wsid1", "v1", {})
    retrieved = layer.get_session(s.session_id)
    assert retrieved is s


def test_layer_get_session_missing(layer):
    assert layer.get_session("no-such-id") is None


def test_layer_end_session(layer):
    s = layer.create_session("user1", "wsid1", "v1", {})
    sid = s.session_id
    layer.end_session(sid)
    assert sid not in layer.sessions


def test_layer_end_session_noop_on_missing(layer):
    # Should not raise
    layer.end_session("nonexistent")


def test_two_sessions_different_ids(layer):
    s1 = layer.create_session("user1", "wsid1", "v1", {})
    s2 = layer.create_session("user1", "wsid1", "v1", {})
    assert s1.session_id != s2.session_id
    assert len(layer.sessions) == 2


async def test_layer_run_turn_yields_layer_events(layer):
    s = layer.create_session("user1", "wsid1", "v1", {})
    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    types = [e["type"] for e in events]
    assert "agent_text_delta" in types
    assert "turn_complete" in types

    # turn_count incremented
    assert s.turn_count == 1


async def test_layer_run_turn_unknown_session_raises(layer):
    with pytest.raises(KeyError):
        async for _ in layer.run_turn("no-such-id", "hi"):
            pass


async def test_layer_run_turn_increments_turn_count(layer):
    s = layer.create_session("user1", "wsid1", "v1", {})
    async for _ in layer.run_turn(s.session_id, "first"):
        pass
    async for _ in layer.run_turn(s.session_id, "second"):
        pass
    assert s.turn_count == 2


async def test_tool_use_emits_agent_action(layer):
    """tool_use event for background tool → agent_action with correct phrase."""
    s = layer.create_session("user1", "wsid1", "v1", {})
    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    agent_actions = [e for e in events if e["type"] == "agent_action"]
    assert len(agent_actions) >= 1
    # get_anchors maps to "Reading your schedule"
    actions_text = [e["friendly_text"] for e in agent_actions]
    assert "Reading your schedule" in actions_text


async def test_passthrough_emits_status(layer):
    """send_status_update tool_use → status event with raw text."""
    s = layer.create_session("user1", "wsid1", "v1", {})
    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    status_events = [e for e in events if e["type"] == "status"]
    texts = [e["text"] for e in status_events]
    assert "Still working" in texts


async def test_coalescing_same_tool_deduplicates(layer):
    """Two calls to same background tool within window → same id, second status='running'."""
    s = layer.create_session("user1", "wsid1", "v1", {})
    events = []
    async for event in layer.run_turn(s.session_id, "first turn"):
        events.append(event)
    async for event in layer.run_turn(s.session_id, "second turn"):
        events.append(event)

    # get_anchors appears in both turns — the starting events share the same id
    # within the coalescing window; the second call emits status='running'.
    get_anchors_starting = [
        e for e in events
        if e["type"] == "agent_action"
        and e.get("friendly_text") == "Reading your schedule"
        and e.get("status") == "starting"
    ]
    get_anchors_running = [
        e for e in events
        if e["type"] == "agent_action"
        and e.get("friendly_text") == "Reading your schedule"
        and e.get("status") == "running"
    ]
    assert len(get_anchors_starting) >= 1
    assert len(get_anchors_running) >= 1
    assert get_anchors_starting[0]["id"] == get_anchors_running[0]["id"]


# ---------------------------------------------------------------------------
# Pool integration + interrupt tests (real API signatures)
# ---------------------------------------------------------------------------

async def test_real_api_pool_run_turn_yields_events():
    """Layer works with real-API-signature pool client (str hash, options dict, query_stream)."""
    layer = _make_layer(_RealApiMockPool())
    s = layer.create_session("user1", "wsid1", "v1", {"model": "haiku"})
    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)
    types = [e["type"] for e in events]
    assert "agent_text_delta" in types
    assert "turn_complete" in types
    assert s.turn_count == 1


async def test_cancelled_event_emits_interrupted():
    """Pool {"event": "cancelled"} → layer {"type": "interrupted"} event."""
    layer = _make_layer(_CancellingMockPool())
    s = layer.create_session("user1", "wsid1", "v1", {})
    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)
    types = [e["type"] for e in events]
    assert "interrupted" in types
    # interrupted event carries session_id
    interrupted = [e for e in events if e["type"] == "interrupted"]
    assert interrupted[0]["session_id"] == s.session_id


async def test_active_handles_populated_during_turn():
    """session.active_handles contains handle_id while turn is running."""
    handles_seen: list[list[str]] = []

    class _SnapshotPool:
        async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
            return f"handle-{user_id}"

        async def query_stream(self, handle_id, prompt, session_id="default"):
            # We can't easily inspect the session here, so just yield one event
            yield {"type": "result", "final_text": "done", "tokens_used": 1}

        async def release(self, handle_id, *, reusable=False): pass
        async def interrupt(self, handle_id): pass

    layer = _make_layer(_SnapshotPool())
    s = layer.create_session("user1", "wsid1", "v1", {})

    # Wrap run_turn to snapshot active_handles after first event
    first = True
    async for _ in layer.run_turn(s.session_id, "hi"):
        if first:
            handles_seen.append(list(s.active_handles))
            first = False

    # During turn: handle was present
    assert len(handles_seen[0]) == 1
    # After turn: handle removed
    assert s.active_handles == []


async def test_active_handles_cleared_after_turn():
    """session.active_handles is empty after a normal turn completes."""
    layer = _make_layer(_RealApiMockPool())
    s = layer.create_session("user1", "wsid1", "v1", {})
    async for _ in layer.run_turn(s.session_id, "hi"):
        pass
    assert s.active_handles == []


async def test_interrupt_calls_pool_interrupt():
    """Layer.interrupt() calls pool_client.interrupt() on the active handle."""
    pool = _TrackingMockPool()
    layer = _make_layer(pool)
    s = layer.create_session("user1", "wsid1", "v1", {})
    # Simulate active handle
    s.active_handles.append("handle-user1")
    await layer.interrupt(s.session_id)
    assert "handle-user1" in pool.interrupted_handles


async def test_interrupt_noop_when_no_active_turn():
    """Layer.interrupt() with no active handles is a no-op (no error)."""
    pool = _TrackingMockPool()
    layer = _make_layer(pool)
    s = layer.create_session("user1", "wsid1", "v1", {})
    # No active handles
    await layer.interrupt(s.session_id)
    assert pool.interrupted_handles == []


# ---------------------------------------------------------------------------
# session_timeout event on permission timeout
# ---------------------------------------------------------------------------

class _PermissionRequestPool:
    """Pool that emits a control_request event so the gate can time out."""

    def __init__(self):
        self.denied_request_id: str | None = None
        self.deny_decision_sent: bool = False

    async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
        return f"handle-{user_id}"

    async def query_stream(self, handle_id, prompt, session_id="default"):
        yield {
            "event": "control_request",
            "subtype": "can_use_tool",
            "tool_name": "upsert_tasks",
            "tool_input": {"count": 1, "tasks": []},
            "request_id": "req-timeout-001",
        }
        # After control_request is handled (or timed out), yield turn result.
        yield {"type": "result", "final_text": "done", "tokens_used": 1}

    async def send_control_response(
        self, handle_id, *, request_id, subtype, decision, denial_message=None
    ):
        self.denied_request_id = request_id
        self.deny_decision_sent = decision == "deny"

    async def release(self, handle_id, *, reusable=False):
        pass

    async def interrupt(self, handle_id):
        pass


async def test_session_timeout_event_emitted_on_permission_timeout(monkeypatch):
    """When the gate times out, run_turn yields a session_timeout event and ends cleanly."""
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        "interactive_agent_layer.session.get_auto_approve_user_actions",
        lambda: False,
    )

    pool = _PermissionRequestPool()
    layer = _make_layer(pool)
    s = layer.create_session("user1", "wsid1", "v1", {})

    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    types = [e["type"] for e in events]
    assert "session_timeout" in types, f"Expected session_timeout in {types}"

    timeout_events = [e for e in events if e["type"] == "session_timeout"]
    assert len(timeout_events) == 1
    te = timeout_events[0]
    assert te["session_id"] == s.session_id
    assert te["reason"] == "permission_timeout"

    # request_id in session_timeout matches the permission_request sent to the user
    # (the gate's UUID), so the frontend can clear the pending permission modal.
    perm_requests = [e for e in events if e["type"] == "permission_request"]
    assert len(perm_requests) == 1
    assert te["request_id"] == perm_requests[0]["request_id"]

    # session_timeout should be the last event (generator ends after it)
    assert events[-1]["type"] == "session_timeout"


async def test_session_timeout_sends_deny_to_pool(monkeypatch):
    """On permission timeout, the pool receives a deny decision before the session ends."""
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        "interactive_agent_layer.session.get_auto_approve_user_actions",
        lambda: False,
    )

    pool = _PermissionRequestPool()
    layer = _make_layer(pool)
    s = layer.create_session("user1", "wsid1", "v1", {})

    async for _ in layer.run_turn(s.session_id, "hi"):
        pass

    assert pool.deny_decision_sent, "Pool must receive deny decision on timeout"
    assert pool.denied_request_id == "req-timeout-001"


async def test_interrupt_unknown_session_noop():
    """Layer.interrupt() on unknown session_id is a no-op (no error)."""
    layer = _make_layer(_RealApiMockPool())
    # Should not raise
    await layer.interrupt("no-such-session")


# ---------------------------------------------------------------------------
# Scope-gating wiring — Layer.run_turn activates the dormant PermissionGate
# scope seam (Task #3). Layer-level hop_distance_fn/resolve_node_path_fn/
# resolve_conversation_scope_fn are (user_id, ...) -> ... shaped (a single
# instance works across all sessions/users); run_turn wraps each with the
# current session's user_id bound in before passing to PermissionGate.
# ---------------------------------------------------------------------------

class _ReadContextControlPool:
    """Pool that emits a control_request for read_context, then completes."""

    def __init__(self, node_ids=None):
        self._node_ids = node_ids if node_ids is not None else ["far-node"]
        self.decisions: list[str] = []
        self.denial_messages: list[str | None] = []

    async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
        return f"handle-{user_id}"

    async def query_stream(self, handle_id, prompt, session_id="default"):
        yield {
            "event": "control_request",
            "subtype": "can_use_tool",
            "tool_name": "read_context",
            "tool_input": {"node_ids": self._node_ids},
            "request_id": "req-scope-001",
        }
        yield {"type": "result", "final_text": "done", "tokens_used": 1}

    async def send_control_response(
        self, handle_id, *, request_id, subtype, decision, denial_message=None
    ):
        self.decisions.append(decision)
        self.denial_messages.append(denial_message)

    async def release(self, handle_id, *, reusable=False):
        pass

    async def interrupt(self, handle_id):
        pass


def _scope_requests(events: list[dict]) -> list[dict]:
    return [
        e for e in events
        if e.get("type") == "permission_request" and e.get("kind") == "read_out_of_scope"
    ]


async def test_run_turn_wires_scope_from_session_options(monkeypatch):
    """scope_source_node_id/scope_radius in session.options + Layer.hop_distance_fn
    activate scope gating: an out-of-range read_context target emits
    read_out_of_scope and, on timeout, is denied."""
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout", lambda: 0.01
    )

    pool = _ReadContextControlPool(node_ids=["far-node"])
    calls: list[tuple[str, str, str]] = []

    async def hop_distance_fn(user_id, from_id, to_id):
        calls.append((user_id, from_id, to_id))
        return 10  # beyond radius

    layer = _make_layer(pool)
    layer.hop_distance_fn = hop_distance_fn

    s = layer.create_session(
        "user1", "wsid1", "v1",
        options={"scope_source_node_id": "source-node", "scope_radius": 2},
    )

    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    assert calls == [("user1", "source-node", "far-node")]
    assert len(_scope_requests(events)) == 1
    assert pool.decisions == ["deny"]  # timed out, no approval


async def test_run_turn_in_scope_target_allows_without_prompt(monkeypatch):
    """In-scope read_context target is auto-allowed with no permission_request."""
    pool = _ReadContextControlPool(node_ids=["near-node"])

    async def hop_distance_fn(user_id, from_id, to_id):
        return 1  # within radius

    layer = _make_layer(pool)
    layer.hop_distance_fn = hop_distance_fn

    s = layer.create_session(
        "user1", "wsid1", "v1",
        options={"scope_source_node_id": "source-node", "scope_radius": 2},
    )

    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    assert _scope_requests(events) == []
    assert pool.decisions == ["allow"]


async def test_run_turn_no_scope_config_is_backwards_compatible():
    """No scope keys in options, no Layer scope fns → no gating (existing behavior)."""
    pool = _ReadContextControlPool(node_ids=["any-node"])
    layer = _make_layer(pool)

    s = layer.create_session("user1", "wsid1", "v1", options={})

    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    assert _scope_requests(events) == []
    assert pool.decisions == ["allow"]


async def test_run_turn_resolves_scope_from_conversation_id(monkeypatch):
    """No explicit scope options — resolve_conversation_scope_fn resolves
    scope_source_node_id from conversation_id, scope_radius from config."""
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout", lambda: 0.01
    )
    monkeypatch.setattr(
        "interactive_agent_layer.session.get_scope_radius", lambda: 2
    )

    pool = _ReadContextControlPool(node_ids=["far-node"])

    resolve_calls: list[tuple[str, str]] = []

    async def resolve_conversation_scope_fn(user_id, conversation_id):
        resolve_calls.append((user_id, conversation_id))
        return "resolved-node"

    async def hop_distance_fn(user_id, from_id, to_id):
        assert from_id == "resolved-node"
        return 10  # beyond the config-default radius of 2

    layer = _make_layer(pool)
    layer.hop_distance_fn = hop_distance_fn
    layer.resolve_conversation_scope_fn = resolve_conversation_scope_fn

    s = layer.create_session(
        "user1", "wsid1", "v1", options={}, conversation_id="conv-1",
    )

    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    assert resolve_calls == [("user1", "conv-1")]
    assert len(_scope_requests(events)) == 1


async def test_run_turn_conversation_scope_resolves_to_none_disables_gating():
    """Conversation has no context_node_id → resolve returns None → no gating."""
    pool = _ReadContextControlPool(node_ids=["any-node"])

    async def resolve_conversation_scope_fn(user_id, conversation_id):
        return None

    hop_calls: list[tuple] = []

    async def hop_distance_fn(user_id, from_id, to_id):
        hop_calls.append((user_id, from_id, to_id))
        return 10

    layer = _make_layer(pool)
    layer.hop_distance_fn = hop_distance_fn
    layer.resolve_conversation_scope_fn = resolve_conversation_scope_fn

    s = layer.create_session(
        "user1", "wsid1", "v1", options={}, conversation_id="conv-1",
    )

    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    assert hop_calls == []  # scope_source_node_id is None → never reaches hop check
    assert _scope_requests(events) == []
    assert pool.decisions == ["allow"]


async def test_layer_accepts_scope_fns_in_constructor():
    """Layer.__init__ accepts hop_distance_fn/resolve_node_path_fn/
    resolve_conversation_scope_fn kwargs (mirrors check_grant_fn/insert_grant_fn)."""
    async def hop_distance_fn(user_id, from_id, to_id):
        return 1

    async def resolve_node_path_fn(user_id, path):
        return "node-id"

    async def resolve_conversation_scope_fn(user_id, conversation_id):
        return "node-id"

    layer = Layer(
        pool_client=_RealApiMockPool(),
        ws_publisher=WSPublisher(),
        hop_distance_fn=hop_distance_fn,
        resolve_node_path_fn=resolve_node_path_fn,
        resolve_conversation_scope_fn=resolve_conversation_scope_fn,
    )
    assert layer.hop_distance_fn is hop_distance_fn
    assert layer.resolve_node_path_fn is resolve_node_path_fn
    assert layer.resolve_conversation_scope_fn is resolve_conversation_scope_fn
