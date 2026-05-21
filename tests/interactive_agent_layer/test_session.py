"""Tests for Session dataclass and Layer class."""
from __future__ import annotations

import pytest
from interactive_agent_layer.session import Session, Layer
from interactive_agent_layer.ws_publisher import WSPublisher


class _MockPoolClient:
    async def acquire(self, user_id: str, options_hash: int) -> str:
        return f"mock-handle-{user_id}"

    async def query(self, handle: str, prompt: str):
        yield {"type": "text_delta", "delta": "Hello "}
        yield {"type": "text_delta", "delta": "world"}
        yield {"type": "result", "final_text": "Hello world", "tokens_used": 42}

    async def release(self, handle: str, reusable: bool = True) -> None:
        pass

    async def interrupt(self, handle: str) -> None:
        pass


@pytest.fixture
def layer():
    publisher = WSPublisher()
    pool = _MockPoolClient()
    return Layer(pool_client=pool, ws_publisher=publisher)


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
