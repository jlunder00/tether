"""Tests for Session dataclass and Layer class."""
from __future__ import annotations

import pytest

from interactive_agent_layer.session import Session


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
    actions_text = [e["action"] for e in agent_actions]
    assert "Reading your schedule" in actions_text


async def test_passthrough_emits_status(layer):
    """send_status_update tool_use → status event with raw text."""
    s = layer.create_session("user1", "wsid1", "v1", {})
    events = []
    async for event in layer.run_turn(s.session_id, "hi"):
        events.append(event)

    status_events = [e for e in events if e["type"] == "status"]
    messages = [e["message"] for e in status_events]
    assert "Still working" in messages


async def test_coalescing_same_tool_deduplicates(layer):
    """Two calls to same background tool within window → same action_id, second coalesced."""
    s = layer.create_session("user1", "wsid1", "v1", {})
    events = []
    async for event in layer.run_turn(s.session_id, "first turn"):
        events.append(event)
    async for event in layer.run_turn(s.session_id, "second turn"):
        events.append(event)

    # get_anchors appears in both turns — second should be coalesced
    get_anchors_events = [
        e for e in events
        if e["type"] == "agent_action" and e.get("action") == "Reading your schedule"
    ]
    assert len(get_anchors_events) == 2
    assert get_anchors_events[0]["action_id"] == get_anchors_events[1]["action_id"]
    assert get_anchors_events[1]["coalesced"] is True
