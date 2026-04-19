import pytest
from db.pg_queries import create_session


@pytest.mark.asyncio
async def test_get_sessions_empty(api_client, conn):
    resp = await api_client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert len(data["sessions"]) == 0


@pytest.mark.asyncio
async def test_get_active_sessions(api_client, conn):
    sid = await create_session(conn, chat_id="chat-001", max_turns=5)
    resp = await api_client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["id"] == sid
    assert data["sessions"][0]["state"] == "active"


@pytest.mark.asyncio
async def test_closed_sessions_not_returned(api_client, conn):
    await create_session(conn, chat_id="chat-002")
    active_sid = await create_session(conn, chat_id="chat-003")
    resp = await api_client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    ids = [s["id"] for s in data["sessions"]]
    assert active_sid in ids
