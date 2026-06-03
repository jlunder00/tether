"""Failing tests for new event schemas (TDD — written before implementation).

Tests here are pure-Python (no DB). They define the TARGET schemas for
agent_action, permission_request, and status and will fail against the
current implementation, serving as the green line to work toward.

permission_grants DB tests live in tests/db/test_permission_grants.py and
run in the postgres-tests CI lane.
"""
from __future__ import annotations

import asyncio
import pathlib

import pytest

from interactive_agent_layer.permissions import (
    PermissionGate,
    PermissionResultAllow,
    PermissionResultDeny,
)
from interactive_agent_layer.session import Layer, Session
from interactive_agent_layer.translation import TranslationTable
from interactive_agent_layer.ws_publisher import WSPublisher


# ---------------------------------------------------------------------------
# Helpers / pool stubs
# ---------------------------------------------------------------------------

def _yaml_path() -> pathlib.Path:
    return (
        pathlib.Path(__file__).parent.parent.parent
        / "config"
        / "agent_translations.yaml"
    )


def _make_layer(pool_client) -> Layer:
    return Layer(
        pool_client=pool_client,
        ws_publisher=WSPublisher(),
        translation_table=TranslationTable.from_yaml(_yaml_path()),
    )


class _SingleToolPool:
    """One tool_use then result."""
    async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
        return f"h-{user_id}"
    async def query_stream(self, handle_id, prompt, session_id="default"):
        yield {"type": "tool_use", "tool_name": "get_anchors", "args": {}}
        yield {"type": "result", "final_text": "done", "tokens_used": 1}
    async def release(self, handle_id, *, reusable=False): pass
    async def interrupt(self, handle_id): pass


class _SameToolTwicePool:
    """Same tool_use twice (within coalescing window) then result."""
    async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
        return f"h-{user_id}"
    async def query_stream(self, handle_id, prompt, session_id="default"):
        yield {"type": "tool_use", "tool_name": "get_anchors", "args": {}}
        yield {"type": "tool_use", "tool_name": "get_anchors", "args": {}}
        yield {"type": "result", "final_text": "done", "tokens_used": 1}
    async def release(self, handle_id, *, reusable=False): pass
    async def interrupt(self, handle_id): pass


class _TwoToolPool:
    """Two different tool_use events then result."""
    async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
        return f"h-{user_id}"
    async def query_stream(self, handle_id, prompt, session_id="default"):
        yield {"type": "tool_use", "tool_name": "get_anchors", "args": {}}
        yield {"type": "tool_use", "tool_name": "get_plan", "args": {}}
        yield {"type": "result", "final_text": "done", "tokens_used": 1}
    async def release(self, handle_id, *, reusable=False): pass
    async def interrupt(self, handle_id): pass


class _StatusEventPool:
    """Raw SDK status event (phase signal from bot pipeline)."""
    async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
        return f"h-{user_id}"
    async def query_stream(self, handle_id, prompt, session_id="default"):
        yield {"type": "status", "phase": "main_reasoning", "text": "Thinking…"}
        yield {"type": "result", "final_text": "done", "tokens_used": 1}
    async def release(self, handle_id, *, reusable=False): pass
    async def interrupt(self, handle_id): pass


class _PassthroughPool:
    """send_status_update tool_use (passthrough entry)."""
    async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
        return f"h-{user_id}"
    async def query_stream(self, handle_id, prompt, session_id="default"):
        yield {"type": "tool_use", "tool_name": "send_status_update",
               "args": {"text": "Still working"}}
        yield {"type": "result", "final_text": "done", "tokens_used": 1}
    async def release(self, handle_id, *, reusable=False): pass
    async def interrupt(self, handle_id): pass


# ---------------------------------------------------------------------------
# agent_action — new schema
# ---------------------------------------------------------------------------

async def test_agent_action_has_new_schema_fields():
    """tool_use -> agent_action must carry id, tool_name, friendly_text, status."""
    layer = _make_layer(_SingleToolPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    actions = [e for e in events if e["type"] == "agent_action"]
    assert actions, "Expected at least one agent_action"
    a = actions[0]

    # New required fields
    assert "id" in a, "agent_action must have 'id' (was action_id)"
    assert "tool_name" in a, "agent_action must have 'tool_name'"
    assert "friendly_text" in a, "agent_action must have 'friendly_text' (was action)"
    assert "status" in a, "agent_action must have 'status'"

    # Old fields gone
    assert "action_id" not in a, "must not carry old 'action_id'"
    assert "action" not in a, "must not carry old 'action'"
    assert "coalesced" not in a, "must not carry old 'coalesced'"


async def test_agent_action_friendly_text_from_translation_table():
    """friendly_text is populated from the YAML translation table."""
    layer = _make_layer(_SingleToolPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    starting = [e for e in events
                if e["type"] == "agent_action" and e.get("status") == "starting"]
    assert starting
    assert starting[0]["friendly_text"] == "Reading your schedule"
    assert starting[0]["tool_name"] == "get_anchors"


async def test_agent_action_status_starting_on_first_call():
    """First tool_use for a tool -> status='starting'."""
    layer = _make_layer(_SingleToolPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    starting = [e for e in events
                if e["type"] == "agent_action" and e.get("status") == "starting"]
    assert starting, "Expected at least one agent_action with status='starting'"


async def test_agent_action_status_running_on_repeated_call():
    """Repeated tool_use within coalescing window -> same id, status='running'."""
    layer = _make_layer(_SameToolTwicePool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    # Filter to the non-complete agent_action events (starting + running).
    # The complete event is also emitted for the same tool when result arrives.
    actions = [
        e for e in events
        if e["type"] == "agent_action"
        and e.get("tool_name") == "get_anchors"
        and e.get("status") != "complete"
    ]
    assert len(actions) == 2, f"Expected 2 non-complete agent_action for get_anchors, got {len(actions)}"
    assert actions[0]["id"] == actions[1]["id"], "Coalesced calls must share 'id'"
    assert actions[0]["status"] == "starting"
    assert actions[1]["status"] == "running"


async def test_agent_action_complete_emitted_before_turn_complete():
    """turn_complete arrival -> complete event for in-flight action emitted first."""
    layer = _make_layer(_SingleToolPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    complete = [e for e in events
                if e["type"] == "agent_action" and e.get("status") == "complete"]
    assert complete, "Expected agent_action with status='complete'"

    complete_idx = next(i for i, e in enumerate(events)
                        if e["type"] == "agent_action" and e.get("status") == "complete")
    tc_idx = next(i for i, e in enumerate(events) if e["type"] == "turn_complete")
    assert complete_idx < tc_idx, "complete must precede turn_complete"


async def test_agent_action_complete_id_matches_starting():
    """complete event carries same id as the starting event for that call."""
    layer = _make_layer(_SingleToolPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    actions = [e for e in events if e["type"] == "agent_action"]
    starting = [a for a in actions if a["status"] == "starting"]
    complete = [a for a in actions if a["status"] == "complete"]
    assert starting and complete
    assert starting[0]["id"] == complete[0]["id"]


async def test_agent_action_complete_emitted_when_different_tool_arrives():
    """When a second different tool arrives, previous tool gets complete first."""
    layer = _make_layer(_TwoToolPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    actions = [e for e in events if e["type"] == "agent_action"]
    # get_anchors must be complete before get_plan starts
    anchors_complete = next(
        (i for i, a in enumerate(actions)
         if a.get("tool_name") == "get_anchors" and a.get("status") == "complete"),
        None,
    )
    plan_start = next(
        (i for i, a in enumerate(actions)
         if a.get("tool_name") == "get_plan" and a.get("status") == "starting"),
        None,
    )
    assert anchors_complete is not None, "get_anchors must emit complete"
    assert plan_start is not None, "get_plan must emit starting"
    assert anchors_complete < plan_start, "complete(get_anchors) must precede starting(get_plan)"


# ---------------------------------------------------------------------------
# permission_request — new schema
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_timeout(monkeypatch):
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 30,
    )


async def _gate_emit_event(
    table, session, tool_name, args, *, resolve=True,
    check_grant_fn=None, insert_grant_fn=None,
):
    """Run PermissionGate.can_use_tool, capture the emitted event, resolve the future."""
    queue: asyncio.Queue = asyncio.Queue()
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=queue,
        auto_approve_user_actions=False,
        check_grant_fn=check_grant_fn,
        insert_grant_fn=insert_grant_fn,
    )
    task = asyncio.create_task(gate.can_use_tool(tool_name, args, None))
    event = await asyncio.wait_for(queue.get(), timeout=5.0)
    fut = session.permission_pending.get(event.get("request_id"))
    if fut and not fut.done():
        fut.set_result(resolve)
    result = await task
    return result, event


@pytest.fixture
def table():
    return TranslationTable.from_yaml(_yaml_path())


@pytest.fixture
def session():
    return Session(
        session_id="s1", user_id="u1", user_ws_id="ws1",
        agent_version="v1", options={},
    )


async def test_permission_request_new_schema_fields(table, session):
    """permission_request must carry kind, target, reason_from_bot (not summary/details)."""
    _, event = await _gate_emit_event(table, session, "upsert_tasks",
                                      {"count": 3, "tasks": ["t1"]})
    assert "kind" in event, "must have 'kind'"
    assert "target" in event, "must have 'target'"
    assert "reason_from_bot" in event, "must have 'reason_from_bot' (may be None)"
    assert "summary" not in event, "must NOT have old 'summary'"
    assert "details" not in event, "must NOT have old 'details'"


async def test_permission_request_kind_upsert_tasks_is_user_section_edit(table, session):
    _, event = await _gate_emit_event(table, session, "upsert_tasks",
                                      {"count": 1, "tasks": ["t1"]})
    assert event["kind"] == "user_section_edit"


async def test_permission_request_kind_delete_tasks_is_destructive(table, session):
    _, event = await _gate_emit_event(table, session, "delete_tasks",
                                      {"count": 1, "operations": []})
    assert event["kind"] == "destructive"


async def test_permission_request_kind_upsert_context_is_user_section_edit(table, session):
    _, event = await _gate_emit_event(table, session, "upsert_context",
                                      {"subject": "work notes", "nodes": []})
    assert event["kind"] == "user_section_edit"


async def test_permission_request_kind_delete_context_is_destructive(table, session):
    _, event = await _gate_emit_event(table, session, "delete_context",
                                      {"subject": "old notes", "operations": []})
    assert event["kind"] == "destructive"


async def test_permission_request_kind_is_valid_enum(table, session):
    valid_kinds = {"read_out_of_scope", "user_section_edit", "destructive"}
    _, event = await _gate_emit_event(table, session, "upsert_tasks",
                                      {"count": 1, "tasks": []})
    assert event["kind"] in valid_kinds


async def test_permission_request_target_is_human_readable_string(table, session):
    _, event = await _gate_emit_event(table, session, "upsert_tasks",
                                      {"count": 2, "tasks": ["t1", "t2"]})
    assert isinstance(event["target"], str) and event["target"]


async def test_permission_gate_skips_request_when_grant_exists(table, session):
    """check_grant_fn returning True auto-allows without emitting permission_request."""
    async def _has_grant(user_id, conversation_id, target, kind):
        return True

    queue: asyncio.Queue = asyncio.Queue()
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=queue,
        auto_approve_user_actions=False,
        check_grant_fn=_has_grant,
    )
    result = await gate.can_use_tool("upsert_tasks", {"count": 1, "tasks": []}, None)
    assert isinstance(result, PermissionResultAllow)
    assert queue.empty(), "No permission_request should be emitted when grant exists"


async def test_permission_gate_inserts_grant_on_approval(table):
    """On user approval, insert_grant_fn is called with user_id, conversation_id, target, kind."""
    session_with_conv = Session(
        session_id="s2", user_id="u2", user_ws_id="ws2",
        agent_version="v1", options={}, conversation_id="conv-123",
    )
    inserted: list[dict] = []

    async def _no_grant(user_id, conversation_id, target, kind):
        return False

    async def _insert(user_id, conversation_id, target, kind):
        inserted.append({"user_id": user_id, "conv": conversation_id,
                         "target": target, "kind": kind})

    _, event = await _gate_emit_event(
        table, session_with_conv, "upsert_tasks", {"count": 1, "tasks": ["t"]},
        resolve=True, check_grant_fn=_no_grant, insert_grant_fn=_insert,
    )
    assert len(inserted) == 1
    assert inserted[0]["user_id"] == "u2"
    assert inserted[0]["conv"] == "conv-123"


async def test_permission_gate_no_insert_on_denial(table, session):
    """On user denial, insert_grant_fn is NOT called."""
    inserted: list = []

    async def _no_grant(uid, cid, target, kind):
        return False

    async def _insert(uid, cid, target, kind):
        inserted.append(kind)

    _, _ = await _gate_emit_event(
        table, session, "upsert_tasks", {"count": 1, "tasks": []},
        resolve=False, check_grant_fn=_no_grant, insert_grant_fn=_insert,
    )
    assert inserted == []


# ---------------------------------------------------------------------------
# status — new schema (phase + text, not message)
# ---------------------------------------------------------------------------

async def test_status_event_has_phase_and_text_not_message():
    """SDK status event -> layer status with 'phase' and 'text', not 'message'."""
    layer = _make_layer(_StatusEventPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    status_evts = [e for e in events if e["type"] == "status"]
    assert status_evts, "Expected at least one status event"
    ev = status_evts[0]
    assert "phase" in ev, "status must have 'phase'"
    assert "text" in ev, "status must have 'text'"
    assert "message" not in ev, "status must NOT have old 'message'"


async def test_status_phase_forwarded_from_sdk_event():
    """status.phase carries the phase from the SDK event."""
    layer = _make_layer(_StatusEventPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    status_evts = [e for e in events if e["type"] == "status"]
    assert status_evts[0]["phase"] == "main_reasoning"
    assert status_evts[0]["text"] == "Thinking…"


async def test_passthrough_tool_emits_status_with_phase_tool_call():
    """send_status_update passthrough -> status with phase='tool_call'."""
    layer = _make_layer(_PassthroughPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    status_evts = [e for e in events if e["type"] == "status"]
    assert status_evts, "Expected status from send_status_update"
    assert status_evts[0]["phase"] == "tool_call"
    assert status_evts[0]["text"] == "Still working"


async def test_status_phase_valid_enum():
    """status.phase must be a member of the defined enum."""
    layer = _make_layer(_StatusEventPool())
    s = layer.create_session("u1", "ws1", "v1", {})
    events = [e async for e in layer.run_turn(s.session_id, "hi")]

    valid = {"classifier", "main_reasoning", "tool_call", "summarization"}
    for ev in events:
        if ev["type"] == "status":
            assert ev["phase"] in valid, f"Invalid phase: {ev['phase']!r}"
