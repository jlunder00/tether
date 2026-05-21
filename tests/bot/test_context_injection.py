"""Unit tests — build_conversation_context helper (Phase G).

Tests verify that the helper assembles context blocks correctly from
conversation → context_node → sections → parent node summary.
"""
from __future__ import annotations

import pytest
from db.pg_queries.conversations import create_conversation
from db.pg_queries.nodes import create_node
from db.pg_queries.sections import upsert_section
from bot.conversation_context import build_conversation_context


TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn
    async def __aenter__(self):
        return self._conn
    async def __aexit__(self, *_):
        pass


class _FakePool:
    """Minimal pool-like stub that yields the given conn via acquire()."""
    def __init__(self, conn):
        self._conn = conn
    def acquire(self):
        return _AcquireCtx(self._conn)


# ---------------------------------------------------------------------------
# No context_node_id — empty string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_context_node_returns_empty(conn):
    cid = await create_conversation(
        conn, user_id=TEST_USER_ID, name="Bare chat", notification_type="bot",
    )
    pool = _FakePool(conn)
    result = await build_conversation_context(cid, pool, TEST_USER_ID)
    assert result == ""


# ---------------------------------------------------------------------------
# Node with sections — context block returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_with_context_node_returns_block(conn):
    node = await create_node(conn, "My Project")
    await upsert_section(conn, node["id"], "notes", "Important project details.")
    cid = await create_conversation(
        conn,
        user_id=TEST_USER_ID,
        name="Project chat",
        notification_type="bot",
        context_node_id=node["id"],
    )
    pool = _FakePool(conn)
    result = await build_conversation_context(cid, pool, TEST_USER_ID)
    assert result != ""
    assert "My Project" in result
    assert "Important project details." in result


@pytest.mark.asyncio
async def test_root_node_no_parent_summary(conn):
    """Root nodes have no parent — should not raise and should omit parent block."""
    node = await create_node(conn, "Root Node")
    await upsert_section(conn, node["id"], "goals", "Root goals here.")
    cid = await create_conversation(
        conn,
        user_id=TEST_USER_ID,
        name="Root chat",
        notification_type="bot",
        context_node_id=node["id"],
    )
    pool = _FakePool(conn)
    result = await build_conversation_context(cid, pool, TEST_USER_ID)
    assert "Root goals here." in result


# ---------------------------------------------------------------------------
# Conversation with unknown context_node_id (node deleted)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleted_context_node_returns_empty(conn):
    """When context_node_id references a deleted node, return empty string gracefully."""
    node = await create_node(conn, "Temp Node")
    cid = await create_conversation(
        conn,
        user_id=TEST_USER_ID,
        name="Orphan chat",
        notification_type="bot",
        context_node_id=node["id"],
    )
    # Delete the node after linking
    await conn.execute("DELETE FROM context_nodes WHERE id = $1::uuid", node["id"])
    pool = _FakePool(conn)
    result = await build_conversation_context(cid, pool, TEST_USER_ID)
    assert result == ""
