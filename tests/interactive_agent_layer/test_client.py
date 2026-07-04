"""Tests for LayerClient (contracts 7-8)."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from httpx import ASGITransport

from interactive_agent_layer.client import LayerClient


@pytest.fixture
async def layer_client_with_app(layer):
    """LayerClient backed by ASGI test transport."""
    from interactive_agent_layer.server import create_app

    app = create_app(layer)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as http:
        lc = LayerClient("http://test")
        lc._client = http
        yield lc


async def test_start_session_returns_session_id(layer_client_with_app):
    """Contract #7: LayerClient.start_session returns session_id string."""
    lc = layer_client_with_app
    sid = await lc.start_session(
        user_id="user1",
        user_ws_id="wsid1",
        agent_version="v1",
        options={},
        user_message="hello",
    )
    assert isinstance(sid, str)
    assert len(sid) > 0


async def test_start_session_forwards_conversation_id(layer_client_with_app, layer):
    """conversation_id passed to start_session reaches Session.conversation_id."""
    lc = layer_client_with_app
    sid = await lc.start_session(
        user_id="user1",
        user_ws_id="wsid1",
        agent_version="v1",
        options={},
        user_message="hello",
        conversation_id="conv-xyz",
    )
    assert layer.sessions[sid].conversation_id == "conv-xyz"


async def test_start_session_conversation_id_optional(layer_client_with_app, layer):
    """conversation_id defaults to None — backwards compatible with existing callers."""
    lc = layer_client_with_app
    sid = await lc.start_session(
        user_id="user1",
        user_ws_id="wsid1",
        agent_version="v1",
        options={},
        user_message="hello",
    )
    assert layer.sessions[sid].conversation_id is None


async def test_end_session(layer_client_with_app, layer):
    """Contract #8: LayerClient.end_session calls POST /session/{id}/end."""
    lc = layer_client_with_app
    sid = await lc.start_session(
        user_id="user2",
        user_ws_id="wsid2",
        agent_version="v1",
        options={},
        user_message="bye",
    )
    assert sid in layer.sessions
    await lc.end_session(sid)
    assert sid not in layer.sessions


async def test_interrupt(layer_client_with_app, layer):
    lc = layer_client_with_app
    sid = await lc.start_session(
        user_id="user3",
        user_ws_id="wsid3",
        agent_version="v1",
        options={},
        user_message="stop",
    )
    # Should not raise
    await lc.interrupt(sid)


async def test_get_status(layer_client_with_app):
    lc = layer_client_with_app
    sid = await lc.start_session(
        user_id="user4",
        user_ws_id="wsid4",
        agent_version="v1",
        options={},
        user_message="status?",
    )
    status = await lc.get_status(sid)
    assert status["session_id"] == sid
    assert status["user_id"] == "user4"


async def test_respond_to_permission_resolves_future_approve(layer_client_with_app, layer):
    """LayerClient.respond_to_permission POSTs {"approve": True} and resolves the future."""
    lc = layer_client_with_app
    sid = await lc.start_session(
        user_id="user6", user_ws_id="wsid6", agent_version="v1",
        options={}, user_message="approve me",
    )
    session = layer.sessions[sid]
    fut = asyncio.get_event_loop().create_future()
    session.permission_pending["req-42"] = fut

    await lc.respond_to_permission("req-42", True)

    assert fut.done()
    assert fut.result() is True


async def test_respond_to_permission_resolves_future_deny(layer_client_with_app, layer):
    """LayerClient.respond_to_permission POSTs {"approve": False} and resolves the future."""
    lc = layer_client_with_app
    sid = await lc.start_session(
        user_id="user7", user_ws_id="wsid7", agent_version="v1",
        options={}, user_message="deny me",
    )
    session = layer.sessions[sid]
    fut = asyncio.get_event_loop().create_future()
    session.permission_pending["req-43"] = fut

    await lc.respond_to_permission("req-43", False)

    assert fut.done()
    assert fut.result() is False


async def test_respond_to_permission_not_found_raises(layer_client_with_app):
    """A request_id with no pending future (already resolved / never existed) raises."""
    lc = layer_client_with_app
    with pytest.raises(httpx.HTTPStatusError):
        await lc.respond_to_permission("no-such-request", True)


async def test_turn_yields_events(layer_client_with_app):
    lc = layer_client_with_app
    sid = await lc.start_session(
        user_id="user5",
        user_ws_id="wsid5",
        agent_version="v1",
        options={},
        user_message="stream me",
    )
    events = []
    async for event in lc.turn(sid, "hello agent"):
        events.append(event)

    types = [e["type"] for e in events]
    assert "agent_text_delta" in types
    assert "turn_complete" in types
