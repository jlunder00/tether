"""Unit tests for M-level cascade depth gating in execute_read_context.

Mocks all DB calls — no Postgres required.
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
    """Return a list of patch context managers covering all DB calls in read_context."""
    async def fake_get_children(conn, parent_id):
        return children_map.get(str(parent_id) if parent_id else None, [])

    async def fake_get_node(conn, node_id):
        return nodes.get(str(node_id))

    async def fake_get_node_by_path(conn, path):
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
        patch(
            "db.pg_queries.node_memory.get_node_tree_distance",
            new=AsyncMock(return_value=1),
        ),
        patch("db.pg_queries.node_memory.get_node_summary", new=AsyncMock(return_value=None)),
        patch("tether_mcp.write_modes.format_cat_n", side_effect=lambda x: x),
        patch("tether_mcp.write_modes.line_count", return_value=1),
    ]


@pytest.mark.asyncio
async def test_cascade_stops_at_N_depth_from_source():
    """Children exactly N levels from source are included; their children are not fetched."""
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
             patches[5], patches[6], patches[7], patches[8], patches[9], patches[10]:
            yield

    async with apply_patches():
        from tether_mcp.tools.read_context import execute_read_context
        result = await execute_read_context(
            conn,
            paths=["Root"],
            depth=-1,
            conversation_id="conv-1",
            N=1,
        )

    assert isinstance(result, list)
    assert len(result) == 1
    root_r = result[0]
    assert "children" in root_r, "Root should have children key (depth > 0)"
    assert len(root_r["children"]) == 1
    child_r = root_r["children"][0]
    # Grandchild is at depth 2 > N=1 — cascade must NOT recurse into it
    assert "children" not in child_r or len(child_r.get("children", [])) == 0, (
        "Children at cascade depth == N should not have their own children fetched"
    )


@pytest.mark.asyncio
async def test_cascade_includes_nodes_up_to_and_including_N():
    """Nodes at depth == N from source are in the result; they are just not expanded."""
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
             patches[5], patches[6], patches[7], patches[8], patches[9], patches[10]:
            yield

    async with apply_patches():
        from tether_mcp.tools.read_context import execute_read_context
        result = await execute_read_context(
            conn,
            paths=["Root"],
            depth=-1,
            conversation_id="conv-1",
            N=1,
        )

    root_r = result[0]
    assert "children" in root_r
    child_ids = [c.get("id") or c.get("name") for c in root_r["children"]]
    assert "child" in child_ids, "Child at depth 1 == N should be included"


@pytest.mark.asyncio
async def test_cascade_unlimited_when_N_is_zero():
    """N=0 means no M-gating — traverse all children (backward compat)."""
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
             patches[5], patches[6], patches[7], patches[8], patches[9], patches[10]:
            yield

    async with apply_patches():
        from tether_mcp.tools.read_context import execute_read_context
        result = await execute_read_context(
            conn,
            paths=["Root"],
            depth=-1,
            conversation_id="conv-1",
            N=0,
        )

    root_r = result[0]
    assert "children" in root_r
    child_r = root_r["children"][0]
    # N=0 means no gating — grandchild should be fetched
    assert "children" in child_r, "N=0 should not gate cascade — grandchild must be fetched"


@pytest.mark.asyncio
async def test_cascade_respects_depth_param_independently():
    """depth=1 still limits traversal even when N > depth."""
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
             patches[5], patches[6], patches[7], patches[8], patches[9], patches[10]:
            yield

    async with apply_patches():
        from tether_mcp.tools.read_context import execute_read_context
        result = await execute_read_context(
            conn,
            paths=["Root"],
            depth=1,   # only 1 level
            conversation_id="conv-1",
            N=5,       # N allows 5 levels, but depth caps at 1
        )

    root_r = result[0]
    assert "children" in root_r
    child_r = root_r["children"][0]
    # depth=1 means child has no children key (depth reached 0)
    assert "children" not in child_r, "depth=1 should prevent grandchild from appearing"


@pytest.mark.asyncio
async def test_conversation_id_required():
    """execute_read_context returns error dict when conversation_id is absent."""
    conn = MagicMock()

    async def fake_get_context_node_id(conn, conversation_id):
        return None

    with patch(
        "db.pg_queries.node_memory.get_context_node_id_for_conversation",
        new=AsyncMock(side_effect=fake_get_context_node_id),
    ):
        from tether_mcp.tools.read_context import execute_read_context
        result = await execute_read_context(conn, conversation_id=None)

    assert isinstance(result, dict)
    assert result.get("error") == "conversation_id_required"
