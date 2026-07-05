"""Tests for read_context v3 demotion: pure retrieval, no authorization.

PermissionGate (interactive_agent_layer/permissions.py) is now the SOLE scope
enforcer (design review §5.1). read_context no longer refuses anything itself:

  1. conversation_id is OPTIONAL. When absent, read_context still returns real
     data (no error envelope) — it simply cannot log a read credit.
  2. There is no more out_of_scope error dict anywhere in read_context output.
     Scope is judged upstream by the gate before the tool call is even made.
  3. When conversation_id IS provided, read credits are still logged (for the
     gate's read-before-write bookkeeping elsewhere), but this is bookkeeping,
     not enforcement.

All tests mock the DB layer — no Postgres required.
"""
from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, patch

import pytest

NODE_ID = "cccccccc-0000-0000-0000-000000000001"
CONV_ID = "dddddddd-0000-0000-0000-000000000002"
CURRENT_NODE = "eeeeeeee-0000-0000-0000-000000000003"

# Patch targets for execute_read_context internals.
# Note: get_node_tree_distance is intentionally NOT here — the demoted
# execute_read_context must not call it at all.
PATCH_TARGETS = [
    "db.pg_queries.get_node",
    "db.pg_queries.get_node_by_path",
    "db.pg_queries.get_children",
    "db.pg_queries.node_memory.log_node_read",
    "db.pg_queries.node_memory.get_context_node_id_for_conversation",
]


@pytest.fixture
def conn():
    return AsyncMock()


def _make_mocks() -> dict:
    mocks = {t.split(".")[-1]: AsyncMock() for t in PATCH_TARGETS}
    mocks["get_context_node_id_for_conversation"].return_value = CURRENT_NODE
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
        # get_node_tree_distance must not exist as a call path anymore; if the
        # implementation still imports/calls it, patching it as a stub that
        # raises makes any accidental reintroduction fail loudly.
        stack.enter_context(
            patch(
                "db.pg_queries.node_memory.get_node_tree_distance",
                AsyncMock(side_effect=AssertionError(
                    "execute_read_context must not call get_node_tree_distance "
                    "(scope enforcement lives solely in PermissionGate)"
                )),
            )
        )
        yield mocks


async def _run(conn, mocks, **kwargs):
    with _patch_all(mocks):
        from tether_mcp.tools.read_context import execute_read_context
        return await execute_read_context(conn, **kwargs)


# ---------------------------------------------------------------------------
# conversation_id is optional — pure retrieval, not gated
# ---------------------------------------------------------------------------

class TestConversationIdOptional:
    @pytest.mark.asyncio
    async def test_no_conversation_id_returns_list_not_error(self, conn):
        mocks = _make_mocks()
        result = await _run(conn, mocks, conversation_id=None)
        assert isinstance(result, list), (
            "Without conversation_id, read_context must still return real data, "
            "not an error envelope"
        )

    @pytest.mark.asyncio
    async def test_no_conversation_id_with_node_ids_returns_data(self, conn):
        mocks = _make_mocks()
        result = await _run(conn, mocks, node_ids=[NODE_ID], conversation_id=None)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].get("id") == NODE_ID

    @pytest.mark.asyncio
    async def test_no_conversation_id_with_paths_returns_data(self, conn):
        mocks = _make_mocks()
        result = await _run(conn, mocks, paths=["Work/Alpha"], conversation_id=None)
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_conversation_id_does_not_log_read_credit(self, conn):
        """No conversation context means nothing to log a credit against."""
        mocks = _make_mocks()
        await _run(conn, mocks, node_ids=[NODE_ID], conversation_id=None)
        mocks["log_node_read"].assert_not_called()

    @pytest.mark.asyncio
    async def test_no_conversation_id_does_not_resolve_scope_node(self, conn):
        """No point resolving a context node for scope when nothing enforces scope here."""
        mocks = _make_mocks()
        await _run(conn, mocks, node_ids=[NODE_ID], conversation_id=None)
        mocks["get_context_node_id_for_conversation"].assert_not_called()


# ---------------------------------------------------------------------------
# conversation_id present — read credit bookkeeping only, still no refusals
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
    async def test_with_conversation_id_logs_read_credit(self, conn):
        mocks = _make_mocks()
        await _run(conn, mocks, node_ids=[NODE_ID], conversation_id=CONV_ID)
        mocks["log_node_read"].assert_called_once()

    @pytest.mark.asyncio
    async def test_no_out_of_scope_dict_ever_produced(self, conn):
        """There is no distance/out-of-scope machinery left in read_context at all."""
        mocks = _make_mocks()
        result = await _run(
            conn, mocks, node_ids=[NODE_ID], conversation_id=CONV_ID, traverse_depth=1
        )
        assert isinstance(result, list)
        assert result[0].get("error") != "out_of_scope"
