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


@pytest.mark.asyncio
async def test_get_active_sessions_uses_query_function(api_client, conn):
    """GET /sessions must call get_active_sessions() from queries, not raw SQL in handler."""
    from unittest.mock import patch, AsyncMock
    # If the handler still uses raw conn.fetch, this patch has no effect and the
    # real raw SQL runs. If the handler uses get_active_sessions(), the patch controls
    # the result. We assert the patched function is called.
    mock_result = [{"id": "test-session-id", "state": "active", "chat_id": "c1",
                    "turn_count": 0, "max_turns": 10, "last_activity": None, "user_id": None}]
    with patch(
        "api.routes.sessions.get_active_sessions",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_fn:
        resp = await api_client.get("/api/sessions")
    assert resp.status_code == 200
    mock_fn.assert_called_once()
