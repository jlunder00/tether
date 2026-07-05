"""Unit tests for cascade traverse_depth gating in execute_read_context.

Mocked tests here cover pure cascade-depth mechanics — no Postgres required.
The bottom of the file adds real (non-mocked) Postgres-backed tests per the
brief-1a acceptance criteria: a regression test proving conversation_id=None
still returns real root nodes, and an RLS-hardening test proving a mismatched
explicit user_id returns nothing even on an unscoped connection.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _node(node_id: str, name: str) -> dict:
    return {
        "id": node_id,
        "name": name,
        "path": name,
        "section_types": [],
        "children_count": 0,
    }


def _make_patches(children_map: dict, nodes: dict, conv_node_id=None):
    """Return a list of patch context managers covering all DB calls in read_context.

    Note: get_node_tree_distance is intentionally NOT patched here (the demoted
    execute_read_context no longer imports/calls it — scope enforcement lives
    solely in PermissionGate now).
    """
    async def fake_get_children(conn, parent_id):
        return children_map.get(str(parent_id) if parent_id else None, [])

    async def fake_get_node(conn, node_id, *, user_id=None):
        return nodes.get(str(node_id))

    async def fake_get_node_by_path(conn, path, *, user_id=None):
        for node in nodes.values():
            if node.get("path") == path or node.get("name") == path:
                return node
        return None

    return [
        patch("db.pg_queries.get_node", new=AsyncMock(side_effect=fake_get_node)),
        patch("db.pg_queries.get_node_by_path", new=AsyncMock(side_effect=fake_get_node_by_path)),
        patch("db.pg_queries.get_children", new=AsyncMock(side_effect=fake_get_children)),
        patch("db.pg_queries.get_sections", new=AsyncMock(return_value=[])),
        patch("db.pg_queries.get_node_tasks", new=AsyncMock(return_value=[])),
        patch(
            "db.pg_queries.node_memory.get_context_node_id_for_conversation",
            new=AsyncMock(return_value=conv_node_id),
        ),
        patch("db.pg_queries.node_memory.log_node_read", new=AsyncMock()),
        patch("db.pg_queries.node_memory.get_node_summary", new=AsyncMock(return_value=None)),
        patch("tether_mcp.write_modes.format_cat_n", side_effect=lambda x: x),
        patch("tether_mcp.write_modes.line_count", return_value=1),
    ]


@pytest.mark.asyncio
async def test_cascade_stops_at_traverse_depth_from_source():
    """Children exactly traverse_depth levels from source are included; their
    children are not fetched."""
    root = _node("root", "Root")
    child = _node("child", "Child")
    gc = _node("gc", "Grandchild")

    children_map = {"root": [child], "child": [gc], "gc": []}
    nodes = {"root": root, "child": child, "gc": gc}

    conn = MagicMock()
    patches = _make_patches(children_map, nodes)

    import contextlib

    @contextlib.asynccontextmanager
    async def apply_patches():
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            yield

    async with apply_patches():
        from tether_mcp.tools.read_context import execute_read_context
        result = await execute_read_context(
            conn,
            paths=["Root"],
            depth=-1,
            conversation_id="conv-1",
            traverse_depth=1,
        )

    assert isinstance(result, list)
    assert len(result) == 1
    root_r = result[0]
    assert "children" in root_r, "Root should have children key (depth > 0)"
    assert len(root_r["children"]) == 1
    child_r = root_r["children"][0]
    # Grandchild is at depth 2 > traverse_depth=1 — cascade must NOT recurse into it
    assert "children" not in child_r or len(child_r.get("children", [])) == 0, (
        "Children at cascade depth == traverse_depth should not have their own children fetched"
    )


@pytest.mark.asyncio
async def test_cascade_includes_nodes_up_to_and_including_traverse_depth():
    """Nodes at depth == traverse_depth from source are in the result; they are
    just not expanded."""
    root = _node("root", "Root")
    child = _node("child", "Child")

    children_map = {"root": [child], "child": []}
    nodes = {"root": root, "child": child}

    conn = MagicMock()
    patches = _make_patches(children_map, nodes)

    import contextlib

    @contextlib.asynccontextmanager
    async def apply_patches():
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            yield

    async with apply_patches():
        from tether_mcp.tools.read_context import execute_read_context
        result = await execute_read_context(
            conn,
            paths=["Root"],
            depth=-1,
            conversation_id="conv-1",
            traverse_depth=1,
        )

    root_r = result[0]
    assert "children" in root_r
    child_ids = [c.get("id") or c.get("name") for c in root_r["children"]]
    assert "child" in child_ids, "Child at depth 1 == traverse_depth should be included"


@pytest.mark.asyncio
async def test_cascade_unlimited_when_traverse_depth_is_zero():
    """traverse_depth=0 means no cascade-gating — traverse all children (backward compat)."""
    root = _node("root", "Root")
    child = _node("child", "Child")
    gc = _node("gc", "Grandchild")

    children_map = {"root": [child], "child": [gc], "gc": []}
    nodes = {"root": root, "child": child, "gc": gc}

    conn = MagicMock()
    patches = _make_patches(children_map, nodes)

    import contextlib

    @contextlib.asynccontextmanager
    async def apply_patches():
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            yield

    async with apply_patches():
        from tether_mcp.tools.read_context import execute_read_context
        result = await execute_read_context(
            conn,
            paths=["Root"],
            depth=-1,
            conversation_id="conv-1",
            traverse_depth=0,
        )

    root_r = result[0]
    assert "children" in root_r
    child_r = root_r["children"][0]
    # traverse_depth=0 means no gating — grandchild should be fetched
    assert "children" in child_r, "traverse_depth=0 should not gate cascade — grandchild must be fetched"


@pytest.mark.asyncio
async def test_cascade_respects_depth_param_independently():
    """depth=1 still limits traversal even when traverse_depth > depth."""
    root = _node("root", "Root")
    child = _node("child", "Child")
    gc = _node("gc", "Grandchild")

    children_map = {"root": [child], "child": [gc], "gc": []}
    nodes = {"root": root, "child": child, "gc": gc}

    conn = MagicMock()
    patches = _make_patches(children_map, nodes)

    import contextlib

    @contextlib.asynccontextmanager
    async def apply_patches():
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            yield

    async with apply_patches():
        from tether_mcp.tools.read_context import execute_read_context
        result = await execute_read_context(
            conn,
            paths=["Root"],
            depth=1,   # only 1 level
            conversation_id="conv-1",
            traverse_depth=5,       # allows 5 levels, but depth caps at 1
        )

    root_r = result[0]
    assert "children" in root_r
    child_r = root_r["children"][0]
    # depth=1 means child has no children key (depth reached 0)
    assert "children" not in child_r, "depth=1 should prevent grandchild from appearing"


# ---------------------------------------------------------------------------
# Real-Postgres regression + RLS-hardening acceptance tests (brief-1a)
# ---------------------------------------------------------------------------
# Uses tests/tether_mcp/conftest.py's `conn` fixture: real RLS-scoped
# transactional connection, rolled back after each test. Skips automatically
# without DATABASE_URL.

import uuid as _uuid


@pytest.mark.asyncio
async def test_real_execute_read_context_no_conversation_id_returns_real_roots(conn):
    """Regression test (the #12 lesson): no mocks. A real root context node
    must come back from execute_read_context when conversation_id=None —
    demotion must not silently return nothing or an error dict."""
    from tests.tether_mcp.conftest import TEST_USER_ID

    node_id = str(_uuid.uuid4())
    await conn.execute(
        "INSERT INTO context_nodes (id, user_id, parent_id, name) "
        "VALUES ($1::uuid, $2::uuid, NULL, $3)",
        node_id, TEST_USER_ID, "RealRootBrief1a",
    )

    from tether_mcp.tools.read_context import execute_read_context
    result = await execute_read_context(conn, conversation_id=None)

    assert isinstance(result, list)
    assert any(r.get("id") == node_id for r in result), (
        "Real root node must be returned with conversation_id=None — "
        "read_context is pure retrieval now, not gated on conversation context"
    )


@pytest.mark.asyncio
async def test_rls_hardening_mismatched_user_id_returns_nothing(conn):
    """Defense-in-depth: the explicit user_id bind is a real filter, not a
    no-op — a mismatched user_id must return nothing from the hardened
    node_memory queries even though this connection's session GUC
    (app.current_user_id) is set to TEST_USER_ID and would otherwise permit
    it via RLS alone. (This test uses the GUC-scoped `conn` fixture, not an
    unscoped connection — see tests/db/test_pg_nodes.py's RLS-hardening
    block for the unscoped-connection case and its sandbox caveat: the
    local dev Postgres role is BYPASSRLS, so RLS-as-deny can't be exercised
    directly here; the explicit-bind code path can be, and is, above.)"""
    from tests.tether_mcp.conftest import TEST_USER_ID
    from db.pg_queries.node_memory import log_node_read, get_conversation_reads

    conversation_id = str(_uuid.uuid4())
    node_id = str(_uuid.uuid4())
    other_user_id = str(_uuid.uuid4())
    await conn.execute(
        "INSERT INTO users (id, username, email, password_hash, is_admin) "
        "VALUES ($1::uuid, 'brief1a_other', 'brief1a_other@example.com', 'x', false) "
        "ON CONFLICT DO NOTHING",
        other_user_id,
    )
    await conn.execute(
        "INSERT INTO context_nodes (id, user_id, parent_id, name) "
        "VALUES ($1::uuid, $2::uuid, NULL, $3)",
        node_id, TEST_USER_ID, "RLSHardeningNode",
    )
    await conn.execute(
        "INSERT INTO conversations (id, user_id, name) VALUES ($1::uuid, $2::uuid, $3)",
        conversation_id, TEST_USER_ID, "brief1a RLS hardening test conversation",
    )

    await log_node_read(
        conn, node_id, 4, conversation_id=conversation_id, user_id=TEST_USER_ID,
    )

    # Explicit mismatched user_id must see nothing, independent of the
    # session's app.current_user_id GUC (which is set to TEST_USER_ID here —
    # the point is the explicit bind overrides/ignores that for isolation).
    reads = await get_conversation_reads(conn, conversation_id, user_id=other_user_id)
    assert reads == []
