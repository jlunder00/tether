"""API tests — lightweight index endpoints.

Endpoints under test:
  GET /api/conversations/index   → [{id, title, parent_context_node_id, state, priority, updated_at, message_count}]
  GET /api/nodes/index           → [{id, title, parent_id, path, child_count}]

These are intentionally minimal — no message bodies, no section data.
Used by the frontend to populate trees quickly without N+1 overhead.
"""
from __future__ import annotations

import pytest
from db.pg_queries.conversations import create_conversation
from db.pg_queries.nodes import create_node


TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


async def _insert_message(conn, conversation_id: str, role: str = "user", content: str = "hi") -> str:
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
# GET /api/conversations/index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversations_index_empty(api_client, conn):
    resp = await api_client.get("/api/conversations/index")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_conversations_index_shape(api_client, conn):
    """Each item must have exactly the index fields — no message bodies or extra columns."""
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="My conv", notification_type="bot",
    )
    resp = await api_client.get("/api/conversations/index")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    # Required fields
    assert item["id"] == cid
    assert item["title"] == "My conv"
    assert "parent_context_node_id" in item
    assert "updated_at" in item
    assert "state" in item          # needed for pending badges on first paint
    assert "priority" in item       # needed for priority dots on first paint
    assert "updated_at" in item
    assert "message_count" in item
    # Must NOT expose full conversation detail fields
    assert "body" not in item
    assert "type" not in item


@pytest.mark.asyncio
async def test_conversations_index_state_and_priority(api_client, conn):
    """state and priority are returned so frontend avoids a follow-up upgrade call."""
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Prio test", notification_type="bot",
        priority="high",
    )
    await conn.execute(
        "UPDATE conversations SET state = 'pending' WHERE id = $1::uuid", cid
    )
    resp = await api_client.get("/api/conversations/index")
    assert resp.status_code == 200
    item = next(i for i in resp.json() if i["id"] == cid)
    assert item["state"] == "pending"
    assert item["priority"] == "high"


@pytest.mark.asyncio
async def test_conversations_index_message_count_zero(api_client, conn):
    await create_conversation(
        conn, user_id=TEST_USER_ID, name="Empty", notification_type="bot",
    )
    resp = await api_client.get("/api/conversations/index")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["message_count"] == 0


@pytest.mark.asyncio
async def test_conversations_index_message_count_nonzero(api_client, conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Has msgs", notification_type="bot",
    )
    for _ in range(3):
        await _insert_message(conn, cid)
    resp = await api_client.get("/api/conversations/index")
    assert resp.status_code == 200
    item = next(i for i in resp.json() if i["id"] == cid)
    assert item["message_count"] == 3


@pytest.mark.asyncio
async def test_conversations_index_parent_context_node_id(api_client, conn):
    node = await create_node(conn, "Work")
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Linked", notification_type="bot",
        context_node_id=node["id"],
    )
    resp = await api_client.get("/api/conversations/index")
    assert resp.status_code == 200
    item = next(i for i in resp.json() if i["id"] == cid)
    assert item["parent_context_node_id"] == node["id"]


@pytest.mark.asyncio
async def test_conversations_index_parent_context_node_id_null(api_client, conn):
    await create_conversation(
        conn, user_id=TEST_USER_ID, name="Unlinked", notification_type="bot",
    )
    resp = await api_client.get("/api/conversations/index")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["parent_context_node_id"] is None


@pytest.mark.asyncio
async def test_conversations_index_rls(api_client, api_client_b, conn):
    """User B must not see user A's conversations in the index."""
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Private", notification_type="bot",
    )
    resp_b = await api_client_b.get("/api/conversations/index")
    assert resp_b.status_code == 200
    ids = [i["id"] for i in resp_b.json()]
    assert cid not in ids


@pytest.mark.asyncio
async def test_conversations_index_no_sql_conflict_with_conversation_id_route(api_client, conn):
    """Route /conversations/index must not be shadowed by /conversations/{id}.

    If FastAPI matched 'index' as a conversation_id path param it would 404
    (no conversation has id='index'). Asserting a list response proves the
    literal /index route was matched, not the /{id} handler.
    """
    resp = await api_client.get("/api/conversations/index")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# GET /api/nodes/index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nodes_index_empty(api_client, conn):
    resp = await api_client.get("/api/nodes/index")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_nodes_index_shape(api_client, conn):
    """Each item must have exactly the index fields — no section data."""
    node = await create_node(conn, "Root")
    resp = await api_client.get("/api/nodes/index")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["id"] == node["id"]
    assert item["title"] == "Root"
    assert item["parent_id"] is None
    assert item["path"] == "Root"
    assert "child_count" in item
    # Must NOT expose full node detail
    assert "section_types" not in item
    assert "description" not in item


@pytest.mark.asyncio
async def test_nodes_index_child_count_zero(api_client, conn):
    await create_node(conn, "Leaf")
    resp = await api_client.get("/api/nodes/index")
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["child_count"] == 0


@pytest.mark.asyncio
async def test_nodes_index_child_count_nonzero(api_client, conn):
    parent = await create_node(conn, "Parent")
    await create_node(conn, "Child1", parent_id=parent["id"])
    await create_node(conn, "Child2", parent_id=parent["id"])
    resp = await api_client.get("/api/nodes/index")
    assert resp.status_code == 200
    items = resp.json()
    parent_item = next(i for i in items if i["id"] == parent["id"])
    assert parent_item["child_count"] == 2


@pytest.mark.asyncio
async def test_nodes_index_path_nested(api_client, conn):
    root = await create_node(conn, "Root")
    child = await create_node(conn, "Child", parent_id=root["id"])
    grandchild = await create_node(conn, "GrandChild", parent_id=child["id"])
    resp = await api_client.get("/api/nodes/index")
    assert resp.status_code == 200
    items = {i["id"]: i for i in resp.json()}
    assert items[root["id"]]["path"] == "Root"
    assert items[child["id"]]["path"] == "Root/Child"
    assert items[grandchild["id"]]["path"] == "Root/Child/GrandChild"


@pytest.mark.asyncio
async def test_nodes_index_parent_id(api_client, conn):
    root = await create_node(conn, "Root")
    child = await create_node(conn, "Child", parent_id=root["id"])
    resp = await api_client.get("/api/nodes/index")
    assert resp.status_code == 200
    items = {i["id"]: i for i in resp.json()}
    assert items[root["id"]]["parent_id"] is None
    assert items[child["id"]]["parent_id"] == root["id"]


@pytest.mark.asyncio
async def test_nodes_index_excludes_archived(api_client, conn):
    live = await create_node(conn, "Live")
    archived = await create_node(conn, "Archived")
    await conn.execute(
        "UPDATE context_nodes SET archived = TRUE WHERE id = $1::uuid", archived["id"]
    )
    resp = await api_client.get("/api/nodes/index")
    assert resp.status_code == 200
    ids = [i["id"] for i in resp.json()]
    assert live["id"] in ids
    assert archived["id"] not in ids


@pytest.mark.asyncio
async def test_nodes_index_rls(api_client, api_client_b, conn):
    """User B must not see user A's nodes in the index.

    The nodes index relies solely on RLS (no explicit user_id filter in the
    query) — this test is the primary guard against an RLS misconfiguration.
    """
    node = await create_node(conn, "PrivateNode")
    resp_b = await api_client_b.get("/api/nodes/index")
    assert resp_b.status_code == 200
    ids = [i["id"] for i in resp_b.json()]
    assert node["id"] not in ids


@pytest.mark.asyncio
async def test_nodes_index_no_sql_conflict_with_node_id_route(api_client, conn):
    """Route /nodes/index must not be shadowed by /nodes/{node_id}."""
    resp = await api_client.get("/api/nodes/index")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
