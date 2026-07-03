"""API tests — Conversations endpoints (Phase G).

Endpoints under test:
  GET    /api/conversations                  list conversations
  POST   /api/conversations                  create conversation
  GET    /api/conversations/{id}             get single conversation
  PATCH  /api/conversations/{id}             patch conversation
  GET    /api/conversations/{id}/messages    list messages (cursor paginated)
  PUT    /api/preferences/notifications      notification routing prefs
  GET    /api/context-nodes/{id}/summary     context node summary
"""
from __future__ import annotations

import pytest
from db.pg_queries.conversations import create_conversation
from db.pg_queries.nodes import create_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


async def _insert_message(conn, conversation_id: str, role: str = "user", content: str = "hello") -> str:
    """Insert a conversation_history row bound to a conversation. Returns the row id."""
    row = await conn.fetchrow(
        """
        INSERT INTO conversation_history (user_id, role, body, conversation_id)
        VALUES ($1::uuid, $2, $3, $4::uuid)
        RETURNING id::text
        """,
        TEST_USER_ID, role, content, conversation_id,
    )
    return row["id"]


# ---------------------------------------------------------------------------
# GET /api/conversations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_conversations_empty(api_client, conn):
    resp = await api_client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_conversations_returns_created(api_client, conn):
    await create_conversation(
        conn,
        user_id=TEST_USER_ID,
        name="Daily standup",
        notification_type="bot",
    )
    resp = await api_client.get("/api/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Daily standup"


@pytest.mark.asyncio
async def test_list_conversations_includes_folder_name(api_client, conn):
    node = await create_node(conn, "Work")
    cid = await create_conversation(
        conn,
        user_id=TEST_USER_ID,
        name="Work chat",
        notification_type="bot",
        context_node_id=node["id"],
    )
    resp = await api_client.get("/api/conversations")
    assert resp.status_code == 200
    item = next(c for c in resp.json() if c["id"] == cid)
    assert item["folder_name"] == "Work"


@pytest.mark.asyncio
async def test_list_conversations_folder_name_null_when_no_node(api_client, conn):
    await create_conversation(
        conn,
        user_id=TEST_USER_ID,
        name="No context",
        notification_type="bot",
    )
    resp = await api_client.get("/api/conversations")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["folder_name"] is None


@pytest.mark.asyncio
async def test_list_conversations_filter_by_state(api_client, conn):
    cid_open = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Open one", notification_type="bot",
    )
    cid_closed = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Closed one", notification_type="bot",
    )
    await conn.execute(
        "UPDATE conversations SET state = 'closed' WHERE id = $1::uuid", cid_closed
    )
    resp = await api_client.get("/api/conversations?state=open")
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert cid_open in ids
    assert cid_closed not in ids


@pytest.mark.asyncio
async def test_list_conversations_filter_by_context_node_id(api_client, conn):
    node = await create_node(conn, "Project A")
    cid_with = await create_conversation(
        conn, user_id=TEST_USER_ID, name="With node", notification_type="bot",
        context_node_id=node["id"],
    )
    cid_without = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Without node", notification_type="bot",
    )
    resp = await api_client.get(f"/api/conversations?context_node_id={node['id']}")
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert cid_with in ids
    assert cid_without not in ids


# ---------------------------------------------------------------------------
# POST /api/conversations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_conversation_minimal(api_client, conn):
    resp = await api_client.post("/api/conversations", json={"name": "New chat"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "New chat"
    assert data["type"] == "interactive"
    assert data["priority"] == "normal"
    assert data["state"] == "open"
    assert data["folder_name"] is None


@pytest.mark.asyncio
async def test_create_conversation_missing_name_rejected(api_client, conn):
    resp = await api_client.post("/api/conversations", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_conversation_with_context_node(api_client, conn):
    node = await create_node(conn, "Work")
    resp = await api_client.post(
        "/api/conversations",
        json={"name": "Work chat", "context_node_id": node["id"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["context_node_id"] == node["id"]
    assert data["folder_name"] == "Work"


@pytest.mark.asyncio
async def test_create_conversation_custom_priority(api_client, conn):
    resp = await api_client.post(
        "/api/conversations",
        json={"name": "Urgent", "priority": "high"},
    )
    assert resp.status_code == 201
    assert resp.json()["priority"] == "high"


# ---------------------------------------------------------------------------
# GET /api/conversations/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_conversation_found(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Details test", notification_type="bot",
    )
    resp = await api_client.get(f"/api/conversations/{cid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == cid
    assert data["name"] == "Details test"


@pytest.mark.asyncio
async def test_get_conversation_not_found(api_client, conn):
    resp = await api_client.get("/api/conversations/00000000-0000-0000-0000-000000000099")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/conversations/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_conversation_name(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Old name", notification_type="bot",
    )
    resp = await api_client.patch(f"/api/conversations/{cid}", json={"name": "New name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New name"


@pytest.mark.asyncio
async def test_patch_conversation_priority(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Prio test", notification_type="bot",
    )
    resp = await api_client.patch(f"/api/conversations/{cid}", json={"priority": "high"})
    assert resp.status_code == 200
    assert resp.json()["priority"] == "high"


@pytest.mark.asyncio
async def test_patch_conversation_state(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="State test", notification_type="bot",
    )
    resp = await api_client.patch(f"/api/conversations/{cid}", json={"state": "closed"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "closed"


@pytest.mark.asyncio
async def test_patch_conversation_context_node_id(api_client, conn):
    node = await create_node(conn, "Home")
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Context test", notification_type="bot",
    )
    resp = await api_client.patch(
        f"/api/conversations/{cid}", json={"context_node_id": node["id"]}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["context_node_id"] == node["id"]
    assert data["folder_name"] == "Home"


@pytest.mark.asyncio
async def test_patch_conversation_not_found(api_client, conn):
    resp = await api_client.patch(
        "/api/conversations/00000000-0000-0000-0000-000000000099",
        json={"name": "ghost"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/conversations/{id}/messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_messages_empty(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Empty msgs", notification_type="bot",
    )
    resp = await api_client.get(f"/api/conversations/{cid}/messages")
    assert resp.status_code == 200
    data = resp.json()
    # Must use "messages" key (not "items") to match frontend MessagesPage type
    assert "messages" in data, f"expected 'messages' key in response, got keys: {list(data.keys())}"
    assert "items" not in data, "must not expose 'items' key — frontend expects 'messages'"
    assert data["messages"] == []
    assert data["has_more"] is False


@pytest.mark.asyncio
async def test_get_messages_returns_messages(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Has msgs", notification_type="bot",
    )
    await _insert_message(conn, cid, role="user", content="Hello")
    await _insert_message(conn, cid, role="assistant", content="Hi there")
    resp = await api_client.get(f"/api/conversations/{cid}/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data, f"expected 'messages' key, got: {list(data.keys())}"
    assert len(data["messages"]) == 2
    roles = {m["role"] for m in data["messages"]}
    assert roles == {"user", "assistant"}
    # Must expose "body" field (not "content") to match frontend ConversationMessage type
    for msg in data["messages"]:
        assert "body" in msg, f"expected 'body' field in message, got: {list(msg.keys())}"
        assert "content" not in msg, "must not expose 'content' — frontend expects 'body'"


@pytest.mark.asyncio
async def test_get_messages_before_id_cursor(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Cursor test", notification_type="bot",
    )
    ids = []
    for i in range(5):
        mid = await _insert_message(conn, cid, content=f"msg {i}")
        ids.append(mid)
    # Fetch with before_id = third message — should return first two only
    cursor_id = ids[2]
    resp = await api_client.get(f"/api/conversations/{cid}/messages?before_id={cursor_id}&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data, f"expected 'messages' key, got: {list(data.keys())}"
    returned_ids = [m["id"] for m in data["messages"]]
    assert ids[0] in returned_ids
    assert ids[1] in returned_ids
    assert cursor_id not in returned_ids
    assert ids[3] not in returned_ids


@pytest.mark.asyncio
async def test_get_messages_has_more_true(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="has_more test", notification_type="bot",
    )
    for i in range(5):
        await _insert_message(conn, cid, content=f"msg {i}")
    resp = await api_client.get(f"/api/conversations/{cid}/messages?limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data, f"expected 'messages' key, got: {list(data.keys())}"
    assert len(data["messages"]) == 3
    assert data["has_more"] is True


@pytest.mark.asyncio
async def test_get_messages_has_more_false(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="has_more false test", notification_type="bot",
    )
    for i in range(3):
        await _insert_message(conn, cid, content=f"msg {i}")
    resp = await api_client.get(f"/api/conversations/{cid}/messages?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data, f"expected 'messages' key, got: {list(data.keys())}"
    assert data["has_more"] is False


@pytest.mark.asyncio
async def test_get_messages_conversation_not_found(api_client, conn):
    resp = await api_client.get(
        "/api/conversations/00000000-0000-0000-0000-000000000099/messages"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/preferences/notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_notification_prefs_valid(api_client, conn):
    resp = await api_client.put(
        "/api/preferences/notifications",
        json={"mode": "all", "priority_threshold": "normal", "channels": ["telegram"]},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_put_notification_prefs_persisted(api_client, conn):
    await api_client.put(
        "/api/preferences/notifications",
        json={"mode": "focus", "priority_threshold": "high", "channels": []},
    )
    resp = await api_client.get("/api/preferences/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "focus"
    assert data["priority_threshold"] == "high"


@pytest.mark.asyncio
async def test_put_notification_prefs_invalid_mode_rejected(api_client, conn):
    resp = await api_client.put(
        "/api/preferences/notifications",
        json={"mode": "unicorn"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/context-nodes/{id}/summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_node_summary_null_when_empty(api_client, conn):
    node = await create_node(conn, "Empty node")
    resp = await api_client.get(f"/api/context-nodes/{node['id']}/summary")
    assert resp.status_code == 200
    assert resp.json()["summary"] is None


@pytest.mark.asyncio
async def test_get_node_summary_returns_value(api_client, conn):
    node = await create_node(conn, "Summarized node")
    await conn.execute(
        "UPDATE context_nodes SET summary = $1 WHERE id = $2::uuid",
        "A brief summary of this node.", node["id"],
    )
    resp = await api_client.get(f"/api/context-nodes/{node['id']}/summary")
    assert resp.status_code == 200
    assert resp.json()["summary"] == "A brief summary of this node."


@pytest.mark.asyncio
async def test_get_node_summary_not_found(api_client, conn):
    resp = await api_client.get(
        "/api/context-nodes/00000000-0000-0000-0000-000000000099/summary"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# RLS isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_conversations_rls_isolation(api_client, api_client_b, conn):
    """User A's conversations must not be visible to user B."""
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="User A private", notification_type="bot",
    )
    resp_b = await api_client_b.get("/api/conversations")
    assert resp_b.status_code == 200
    ids_b = [c["id"] for c in resp_b.json()]
    assert cid not in ids_b


@pytest.mark.asyncio
async def test_get_conversation_rls_isolation(api_client, api_client_b, conn):
    """User B cannot GET a conversation owned by user A."""
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="User A only", notification_type="bot",
    )
    resp_b = await api_client_b.get(f"/api/conversations/{cid}")
    assert resp_b.status_code == 404
