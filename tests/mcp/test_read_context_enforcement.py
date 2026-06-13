"""Tests for read_context v2 enforcement: conversation_id required.

All tests mock the DB layer — no Postgres required.

Enforcement rules (v2):
  1. conversation_id is required — returns {"error": "conversation_id_required", ...}
     immediately if absent (no scope enforcement, no reads).
  2. Scope envelope (out_of_scope errors) are already structured dicts — verified here.
  3. When conversation_id is provided, execution proceeds normally.
"""
from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, patch

import pytest

NODE_ID = "cccccccc-0000-0000-0000-000000000001"
CONV_ID = "dddddddd-0000-0000-0000-000000000002"
CURRENT_NODE = "eeeeeeee-0000-0000-0000-000000000003"

# Patch targets for execute_read_context internals
PATCH_TARGETS = [
    "db.pg_queries.get_node",
    "db.pg_queries.get_node_by_path",
    "db.pg_queries.get_children",
    "db.pg_queries.node_memory.log_node_read",
    "db.pg_queries.node_memory.get_context_node_id_for_conversation",
    "db.pg_queries.node_memory.get_node_tree_distance",
]


@pytest.fixture
def conn():
    return AsyncMock()


def _make_mocks() -> dict:
    mocks = {t.split(".")[-1]: AsyncMock() for t in PATCH_TARGETS}
    # Default: conversation is linked to CURRENT_NODE, nodes are in scope
    mocks["get_context_node_id_for_conversation"].return_value = CURRENT_NODE
    mocks["get_node_tree_distance"].return_value = 1  # within N=3
    mocks["get_node"].return_value = {
        "id": NODE_ID, "name": "Test Node",
        "section_types": [], "children_count": 0,
    }
    mocks["get_node_by_path"].return_value = {
        "id": NODE_ID, "name": "Test Node",
        "section_types": [], "children_count": 0,
    }
    mocks["get_children"].return_value = []
    return mocks


@contextlib.contextmanager
def _patch_all(mocks: dict):
    with contextlib.ExitStack() as stack:
        for t in PATCH_TARGETS:
            key = t.split(".")[-1]
            stack.enter_context(patch(t, mocks[key]))
        yield mocks


async def _run(conn, mocks, **kwargs):
    with _patch_all(mocks):
        from tether_mcp.tools.read_context import execute_read_context
        return await execute_read_context(conn, **kwargs)


# ---------------------------------------------------------------------------
# B-1: conversation_id required
# ---------------------------------------------------------------------------

class TestConversationIdRequired:
    @pytest.mark.asyncio
    async def test_no_conversation_id_returns_error_dict(self, conn):
        mocks = _make_mocks()
        result = await _run(conn, mocks, conversation_id=None)
        assert isinstance(result, dict), (
            "Without conversation_id, result must be a dict error envelope, got list"
        )
        assert result.get("error") == "conversation_id_required"

    @pytest.mark.asyncio
    async def test_no_conversation_id_error_has_message(self, conn):
        mocks = _make_mocks()
        result = await _run(conn, mocks, conversation_id=None)
        assert "message" in result

    @pytest.mark.asyncio
    async def test_no_conversation_id_does_not_query_db(self, conn):
        """No DB calls should happen when conversation_id is missing."""
        mocks = _make_mocks()
        await _run(conn, mocks, conversation_id=None)
        mocks["get_node"].assert_not_called()
        mocks["get_node_by_path"].assert_not_called()
        mocks["get_children"].assert_not_called()
        mocks["get_context_node_id_for_conversation"].assert_not_called()

    @pytest.mark.asyncio
    async def test_no_conversation_id_with_paths_returns_error(self, conn):
        mocks = _make_mocks()
        result = await _run(conn, mocks, paths=["Work/Alpha"], conversation_id=None)
        assert isinstance(result, dict)
        assert result.get("error") == "conversation_id_required"

    @pytest.mark.asyncio
    async def test_no_conversation_id_with_node_ids_returns_error(self, conn):
        mocks = _make_mocks()
        result = await _run(conn, mocks, node_ids=[NODE_ID], conversation_id=None)
        assert isinstance(result, dict)
        assert result.get("error") == "conversation_id_required"


# ---------------------------------------------------------------------------
# B-2: happy path — conversation_id provided
# ---------------------------------------------------------------------------

class TestReadContextWithConversationId:
    @pytest.mark.asyncio
    async def test_with_conversation_id_returns_list(self, conn):
        mocks = _make_mocks()
        result = await _run(conn, mocks, conversation_id=CONV_ID)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_with_node_id_and_conversation_id_returns_list(self, conn):
        mocks = _make_mocks()
        result = await _run(conn, mocks, node_ids=[NODE_ID], conversation_id=CONV_ID)
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_scope_check_is_called_when_conversation_id_provided(self, conn):
        mocks = _make_mocks()
        await _run(conn, mocks, node_ids=[NODE_ID], conversation_id=CONV_ID, N=3)
        mocks["get_context_node_id_for_conversation"].assert_called_once_with(conn, CONV_ID)

    @pytest.mark.asyncio
    async def test_out_of_scope_node_returns_structured_error_dict(self, conn):
        """Out-of-scope nodes return {error: 'out_of_scope', ...} dicts, not exceptions."""
        mocks = _make_mocks()
        # Node is too far away — distance exceeds N
        mocks["get_node_tree_distance"].return_value = None
        result = await _run(conn, mocks, node_ids=[NODE_ID], conversation_id=CONV_ID, N=3)
        assert isinstance(result, list)
        assert len(result) == 1
        entry = result[0]
        assert entry.get("error") == "out_of_scope"
        assert "target" in entry
        assert "message" in entry

    @pytest.mark.asyncio
    async def test_out_of_scope_does_not_raise_exception(self, conn):
        """Scope violations must be structured responses, never unhandled exceptions."""
        mocks = _make_mocks()
        mocks["get_node_tree_distance"].return_value = None
        # Should complete without raising
        result = await _run(conn, mocks, node_ids=[NODE_ID], conversation_id=CONV_ID)
        assert result is not None
