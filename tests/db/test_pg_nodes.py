"""Tests for db/pg_queries/nodes.py — tree traversal, move, cycle detection."""
import pytest

from tests.db.pg_conftest import conn, auth_conn, TEST_USER_ID  # noqa: F401
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
    # get_subtree returns descendants only, not the root itself
    assert {"Child1", "Child2", "Grandchild"}.issubset(names)


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
    inserted = await upsert_tasks(conn, "2026-04-17", anchor_id, [{"text": "linked task", "status": "pending"}])
    tid = inserted[0]["id"]

    node = await create_node(conn, name="TaskNode", node_type="context")
    await link_task_to_node(conn, node["id"], tid)
    tasks = await get_node_tasks(conn, node["id"])
    assert any(t["id"] == tid for t in tasks)

    await unlink_task_from_node(conn, node["id"], tid)
    tasks = await get_node_tasks(conn, node["id"])
    assert not any(t["id"] == tid for t in tasks)


@pytest.mark.asyncio
async def test_get_all_node_paths(conn):
    await ensure_node_path(conn, "AllPaths/Sub/Leaf")
    paths = await get_all_node_paths(conn)
    assert any("AllPaths" in p for p in paths)


# ---------------------------------------------------------------------------
# RLS hardening (0e addendum / brief-1a) — real unscoped-connection tests.
#
# `auth_conn` (tests/db/pg_conftest.py) never sets `app.current_user_id`, so
# these exercise the "defense in depth on an unscoped connection" case the
# hardening addendum targets — unlike the `conn` fixture, which always has
# the GUC set and so can never distinguish "explicit bind" from "GUC
# happened to match".
#
# NOTE on local sandbox limits: the local dev Postgres role connects with
# BYPASSRLS (confirmed: `rolbypassrls=True` for the `tether` role used by
# DATABASE_URL here — see the pre-existing, out-of-scope failure of
# tests/db/test_rls.py::test_app_db_role_is_not_superuser, which asserts
# prod's app role is NOT superuser/bypassrls). That means RLS itself cannot
# be exercised as a *deny* mechanism in this sandbox — a query with no
# explicit user_id and no GUC will still see the row here, whereas in prod
# (non-bypassing app role) RLS would deny it. What CAN be verified here,
# independent of RLS/role privileges, is the actual code path this
# hardening adds: an explicit user_id bind is a real SQL filter, so a
# mismatched user_id must never resolve someone else's node, and a matching
# explicit user_id must resolve it. That's what these tests assert.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_node_by_path_explicit_user_id_resolves_own_node(auth_conn):
    await auth_conn.execute(
        "INSERT INTO context_nodes (id, user_id, parent_id, name) "
        "VALUES (gen_random_uuid(), $1::uuid, NULL, $2)",
        uuid.UUID(TEST_USER_ID), "ExplicitBindRoot",
    )
    found = await get_node_by_path(auth_conn, "ExplicitBindRoot", user_id=TEST_USER_ID)
    assert found is not None
    assert found["name"] == "ExplicitBindRoot"


@pytest.mark.asyncio
async def test_get_node_by_path_mismatched_user_id_returns_none(auth_conn):
    """Explicit user_id binding must actually filter — a mismatched user_id
    must not resolve a node that belongs to someone else."""
    other_user_id = str(uuid.uuid4())
    await auth_conn.execute(
        "INSERT INTO users (id, username, email, password_hash, is_admin) "
        "VALUES ($1::uuid, 'nodes_other', 'nodes_other@example.com', 'x', false) "
        "ON CONFLICT DO NOTHING",
        other_user_id,
    )
    await auth_conn.execute(
        "INSERT INTO context_nodes (id, user_id, parent_id, name) "
        "VALUES (gen_random_uuid(), $1::uuid, NULL, $2)",
        uuid.UUID(TEST_USER_ID), "MismatchRoot",
    )
    result = await get_node_by_path(auth_conn, "MismatchRoot", user_id=other_user_id)
    assert result is None


@pytest.mark.asyncio
async def test_get_node_explicit_user_id_resolves_own_node(auth_conn):
    """get_node gains the same optional user_id explicit-bind hardening as
    get_node_by_path — brief-1a review finding: id-based lookups (used by
    read_context's node_ids branch and the children section_types/
    children_count backfill) previously had no user_id param at all."""
    node_id = str(uuid.uuid4())
    await auth_conn.execute(
        "INSERT INTO context_nodes (id, user_id, parent_id, name) "
        "VALUES ($1::uuid, $2::uuid, NULL, $3)",
        uuid.UUID(node_id), uuid.UUID(TEST_USER_ID), "ExplicitBindGetNode",
    )
    found = await get_node(auth_conn, node_id, user_id=TEST_USER_ID)
    assert found is not None
    assert found["name"] == "ExplicitBindGetNode"


@pytest.mark.asyncio
async def test_get_node_mismatched_user_id_returns_none(auth_conn):
    node_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    await auth_conn.execute(
        "INSERT INTO users (id, username, email, password_hash, is_admin) "
        "VALUES ($1::uuid, 'nodes_other2', 'nodes_other2@example.com', 'x', false) "
        "ON CONFLICT DO NOTHING",
        other_user_id,
    )
    await auth_conn.execute(
        "INSERT INTO context_nodes (id, user_id, parent_id, name) "
        "VALUES ($1::uuid, $2::uuid, NULL, $3)",
        uuid.UUID(node_id), uuid.UUID(TEST_USER_ID), "MismatchGetNode",
    )
    result = await get_node(auth_conn, node_id, user_id=other_user_id)
    assert result is None


@pytest.mark.asyncio
async def test_get_node_user_id_is_optional_backward_compatible(conn):
    """user_id=None (default) preserves old RLS-only behavior on a
    GUC-scoped connection — no regression for existing callers."""
    node = await create_node(conn, name="BackCompatGetNode", node_type="context")
    found = await get_node(conn, node["id"])
    assert found is not None
    assert found["id"] == node["id"]
