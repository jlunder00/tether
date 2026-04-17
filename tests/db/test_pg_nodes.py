"""Tests for db/pg_queries/nodes.py — tree traversal, move, cycle detection."""
import pytest

from tests.db.pg_conftest import conn, TEST_USER_ID  # noqa: F401
from db.pg_queries.nodes import (
    create_node, get_node, get_node_by_path, get_children,
    ensure_node_path, get_all_node_paths, get_subtree,
    move_node, rename_node, delete_node, archive_node, patch_node_fields,
    link_task_to_node, unlink_task_from_node, get_node_tasks,
)
from db.pg_queries.anchors import seed_default_anchors
from db.pg_queries.plans import upsert_plan
from db.pg_queries.tasks import upsert_tasks
import uuid


@pytest.mark.asyncio
async def test_create_and_get_node(conn):
    node = await create_node(conn, name="Projects", node_type="context")
    assert node["name"] == "Projects"
    fetched = await get_node(conn, node["id"])
    assert fetched["id"] == node["id"]


@pytest.mark.asyncio
async def test_get_node_by_path(conn):
    await ensure_node_path(conn, "Work/Backend")
    node = await get_node_by_path(conn, "Work/Backend")
    assert node is not None
    assert node["name"] == "Backend"


@pytest.mark.asyncio
async def test_tree_traversal(conn):
    root = await create_node(conn, name="Root", node_type="context")
    child1 = await create_node(conn, name="Child1", node_type="context", parent_id=root["id"])
    child2 = await create_node(conn, name="Child2", node_type="context", parent_id=root["id"])
    grandchild = await create_node(conn, name="Grandchild", node_type="context", parent_id=child1["id"])

    children = await get_children(conn, root["id"])
    assert {c["name"] for c in children} == {"Child1", "Child2"}

    subtree = await get_subtree(conn, root["id"])
    names = {n["name"] for n in subtree}
    assert {"Root", "Child1", "Child2", "Grandchild"}.issubset(names)


@pytest.mark.asyncio
async def test_move_node(conn):
    parent_a = await create_node(conn, name="ParentA", node_type="context")
    parent_b = await create_node(conn, name="ParentB", node_type="context")
    child = await create_node(conn, name="MoveMe", node_type="context", parent_id=parent_a["id"])

    await move_node(conn, child["id"], parent_b["id"])
    moved = await get_node(conn, child["id"])
    assert moved["parent_id"] == parent_b["id"]


@pytest.mark.asyncio
async def test_cycle_detection(conn):
    """Moving a node to one of its own descendants should raise."""
    root = await create_node(conn, name="CycleRoot", node_type="context")
    child = await create_node(conn, name="CycleChild", node_type="context", parent_id=root["id"])
    with pytest.raises(Exception):
        await move_node(conn, root["id"], child["id"])


@pytest.mark.asyncio
async def test_rename_node(conn):
    node = await create_node(conn, name="OldName", node_type="context")
    await rename_node(conn, node["id"], "NewName")
    fetched = await get_node(conn, node["id"])
    assert fetched["name"] == "NewName"


@pytest.mark.asyncio
async def test_archive_and_patch(conn):
    node = await create_node(conn, name="ArchiveMe", node_type="context")
    await archive_node(conn, node["id"])
    fetched = await get_node(conn, node["id"])
    assert fetched["archived"] is True
    await patch_node_fields(conn, node["id"], {"description": "patched desc"})
    fetched = await get_node(conn, node["id"])
    assert fetched["description"] == "patched desc"
    assert fetched["version"] >= 1


@pytest.mark.asyncio
async def test_link_task_to_node(conn):
    await seed_default_anchors(conn)
    from db.pg_queries.anchors import get_anchors
    anchors = await get_anchors(conn)
    anchor_id = anchors[0]["id"]
    await upsert_plan(conn, "2026-04-17")
    tid = str(uuid.uuid4())
    await upsert_tasks(conn, "2026-04-17", anchor_id, [{"uuid": tid, "text": "linked task", "status": "pending", "position": 0}])

    node = await create_node(conn, name="TaskNode", node_type="context")
    await link_task_to_node(conn, node["id"], tid)
    tasks = await get_node_tasks(conn, node["id"])
    assert tid in tasks

    await unlink_task_from_node(conn, node["id"], tid)
    tasks = await get_node_tasks(conn, node["id"])
    assert tid not in tasks


@pytest.mark.asyncio
async def test_get_all_node_paths(conn):
    await ensure_node_path(conn, "AllPaths/Sub/Leaf")
    paths = await get_all_node_paths(conn)
    path_strings = [p["path"] for p in paths]
    assert any("AllPaths" in p for p in path_strings)
