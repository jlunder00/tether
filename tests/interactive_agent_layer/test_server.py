"""Tests for FastAPI server endpoints (contracts 1-4)."""
from __future__ import annotations

import json

import pytest


async def test_session_start_returns_session_id(layer_client, layer):
    """Contract #1: POST /session/start returns session_id, session in Layer.sessions."""
    resp = await layer_client.post(
        "/session/start",
        json={
            "user_id": "user1",
            "user_ws_id": "wsid1",
            "agent_version": "v1",
            "options": {},
            "user_message": "hello",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    sid = data["session_id"]
    assert sid in layer.sessions


async def test_session_start_threads_conversation_id(layer_client, layer):
    """conversation_id in the /session/start body reaches Session.conversation_id
    (needed so scope-source-node resolution can look up the conversation)."""
    resp = await layer_client.post(
        "/session/start",
        json={
            "user_id": "user1",
            "user_ws_id": "wsid1",
            "agent_version": "v1",
            "options": {},
            "user_message": "hello",
            "conversation_id": "conv-abc",
        },
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    assert layer.sessions[sid].conversation_id == "conv-abc"


async def test_session_start_conversation_id_optional(layer_client, layer):
    """conversation_id is optional — omitting it is fully backwards-compatible."""
    resp = await layer_client.post(
        "/session/start",
        json={
            "user_id": "user1",
            "user_ws_id": "wsid1",
            "agent_version": "v1",
            "options": {},
            "user_message": "hello",
        },
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    assert layer.sessions[sid].conversation_id is None


async def test_session_status(layer_client, layer):
    """Contract #4: GET /session/{id}/status returns state dict."""
    start_resp = await layer_client.post(
        "/session/start",
        json={
            "user_id": "user2",
            "user_ws_id": "wsid2",
            "agent_version": "v1",
            "options": {"k": "v"},
            "user_message": "hi",
        },
    )
    sid = start_resp.json()["session_id"]

    status_resp = await layer_client.get(f"/session/{sid}/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["session_id"] == sid
    assert data["user_id"] == "user2"
    assert data["agent_version"] == "v1"
    assert "turn_count" in data
    assert "created_at" in data


async def test_session_status_not_found(layer_client):
    resp = await layer_client.get("/session/no-such-id/status")
    assert resp.status_code == 404


async def test_session_end(layer_client, layer):
    """Contract #3: POST /session/{id}/end removes session, returns 200."""
    start_resp = await layer_client.post(
        "/session/start",
        json={
            "user_id": "user3",
            "user_ws_id": "wsid3",
            "agent_version": "v1",
            "options": {},
            "user_message": "bye",
        },
    )
    sid = start_resp.json()["session_id"]
    assert sid in layer.sessions

    end_resp = await layer_client.post(f"/session/{sid}/end")
    assert end_resp.status_code == 200
    assert end_resp.json() == {"status": "ended"}
    assert sid not in layer.sessions


async def test_session_end_not_found(layer_client):
    resp = await layer_client.post("/session/no-such-id/end")
    assert resp.status_code == 404


async def test_session_interrupt(layer_client, layer):
    start_resp = await layer_client.post(
        "/session/start",
        json={
            "user_id": "user4",
            "user_ws_id": "wsid4",
            "agent_version": "v1",
            "options": {},
            "user_message": "interrupt me",
        },
    )
    sid = start_resp.json()["session_id"]

    resp = await layer_client.post(f"/session/{sid}/interrupt")
    assert resp.status_code == 200
    assert resp.json() == {"status": "interrupted"}


async def test_session_interrupt_not_found(layer_client):
    resp = await layer_client.post("/session/no-such-id/interrupt")
    assert resp.status_code == 404


async def test_turn_sse_stream(layer_client, layer):
    """Contract #2: POST /session/{id}/turn returns SSE with agent_text_delta then turn_complete."""
    start_resp = await layer_client.post(
        "/session/start",
        json={
            "user_id": "user5",
            "user_ws_id": "wsid5",
            "agent_version": "v1",
            "options": {},
            "user_message": "test",
        },
    )
    sid = start_resp.json()["session_id"]

    events = []
    async with layer_client.stream(
        "POST",
        f"/session/{sid}/turn",
        json={"prompt": "Hello, agent!"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        buffer = ""
        async for chunk in resp.aiter_text():
            buffer += chunk
        # Parse SSE events from buffer
        for block in buffer.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            for line in block.splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    types = [e["type"] for e in events]
    assert "agent_text_delta" in types
    assert "turn_complete" in types

    # Verify session_id is included in events
    for e in events:
        assert e.get("session_id") == sid


async def test_turn_not_found(layer_client):
    resp = await layer_client.post(
        "/session/no-such-id/turn",
        json={"prompt": "hi"},
    )
    assert resp.status_code == 404


async def test_turn_increments_turn_count(layer_client, layer):
    start_resp = await layer_client.post(
        "/session/start",
        json={
            "user_id": "user6",
            "user_ws_id": "wsid6",
            "agent_version": "v1",
            "options": {},
            "user_message": "count me",
        },
    )
    sid = start_resp.json()["session_id"]

    async with layer_client.stream(
        "POST", f"/session/{sid}/turn", json={"prompt": "once"}
    ) as r:
        async for _ in r.aiter_bytes():
            pass

    assert layer.sessions[sid].turn_count == 1


async def test_permission_respond_resolves_future(layer_client, layer):
    """POST /permission/{id}/respond sets the Future in session.permission_pending."""
    import asyncio
    start_resp = await layer_client.post(
        "/session/start",
        json={"user_id": "u1", "user_ws_id": "ws1", "agent_version": "v1", "options": {}, "user_message": "x"},
    )
    sid = start_resp.json()["session_id"]
    session = layer.sessions[sid]

    # Manually plant a future
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    session.permission_pending["req-1"] = fut

    resp = await layer_client.post("/permission/req-1/respond", json={"approve": True})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert fut.done()
    assert fut.result() is True


async def test_permission_respond_not_found(layer_client):
    resp = await layer_client.post("/permission/no-such-id/respond", json={"approve": False})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# turn_error emission — pool failure during run_turn
# ---------------------------------------------------------------------------

async def _collect_sse_events(layer_client, sid: str) -> list[dict]:
    """Helper: POST /session/{sid}/turn and collect all SSE events."""
    events = []
    async with layer_client.stream(
        "POST", f"/session/{sid}/turn", json={"prompt": "fail me"}
    ) as resp:
        assert resp.status_code == 200
        buffer = ""
        async for chunk in resp.aiter_text():
            buffer += chunk
        for block in buffer.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            for line in block.splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
    return events


async def test_turn_error_emitted_when_pool_raises(layer):
    """When pool.acquire() raises, event_generator must emit a turn_error SSE event."""
    from agent_pool_manager.client import PoolClientError
    from interactive_agent_layer.server import create_app
    from httpx import AsyncClient, ASGITransport

    class FailingPoolClient:
        async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
            raise PoolClientError("pool_exhausted — retry after 5s")

        async def query_stream(self, handle_id, prompt, session_id="default"):
            return
            yield  # make it a generator

        async def release(self, handle_id, *, reusable=False):
            pass

        async def interrupt(self, handle_id):
            pass

    from interactive_agent_layer.ws_publisher import WSPublisher
    from interactive_agent_layer.session import Layer
    import pathlib

    yaml_path = pathlib.Path(__file__).parent.parent.parent / "config" / "agent_translations.yaml"
    from interactive_agent_layer.translation import TranslationTable
    failing_layer = Layer(
        pool_client=FailingPoolClient(),
        ws_publisher=WSPublisher(),
        translation_table=TranslationTable.from_yaml(yaml_path),
    )
    app = create_app(failing_layer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start = await client.post(
            "/session/start",
            json={"user_id": "u1", "user_ws_id": "ws1", "agent_version": "v1", "options": {}, "user_message": "x"},
        )
        sid = start.json()["session_id"]

        events = []
        async with client.stream("POST", f"/session/{sid}/turn", json={"prompt": "go"}) as resp:
            assert resp.status_code == 200
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
        for block in buffer.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            for line in block.splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    types = [e["type"] for e in events]
    assert "turn_error" in types, f"turn_error event must be emitted on pool failure, got: {types}"
    error_event = next(e for e in events if e["type"] == "turn_error")
    assert "pool_exhausted" in error_event.get("message", ""), (
        f"turn_error message must include pool error: {error_event}"
    )
