"""Tests for db/pg_queries/tasks.py — including version-conflict (StaleReadError)."""
import pytest
import uuid

from tests.db.pg_conftest import conn, pg_pool, TEST_USER_ID  # noqa: F401
from db.pg_queries.anchors import seed_default_anchors
from db.pg_queries.plans import upsert_plan
from db.pg_queries.tasks import (
    upsert_tasks, patch_task_fields, get_task_by_uuid,
    get_all_tasks, get_unscheduled_tasks, delete_task_by_uuid,
    move_task_atomic, search_tasks,
    add_task_dependency, remove_task_dependency, get_full_task_dependencies,
    get_subtasks, create_subtask, update_subtask, delete_subtask,
)
from db.pg_queries.errors import StaleReadError


DATE = "2026-04-17"


@pytest.fixture
async def anchor_id(conn):
    await seed_default_anchors(conn, TEST_USER_ID)
    from db.pg_queries.anchors import get_anchors
    anchors = await get_anchors(conn)
    return anchors[0]["id"]


@pytest.fixture
async def task_uuid(conn, anchor_id):
    await upsert_plan(conn, DATE)
    tid = str(uuid.uuid4())
    await upsert_tasks(conn, DATE, anchor_id, [{"uuid": tid, "text": "Test task", "status": "pending", "position": 0}])
    return tid


@pytest.mark.asyncio
async def test_upsert_and_get_task(conn, task_uuid):
    task = await get_task_by_uuid(conn, task_uuid)
    assert task is not None
    assert task["text"] == "Test task"
    assert task["status"] == "pending"
    assert task["version"] == 0


@pytest.mark.asyncio
async def test_patch_task_increments_version(conn, task_uuid):
    await patch_task_fields(conn, task_uuid, {"status": "in_progress"})
    task = await get_task_by_uuid(conn, task_uuid)
    assert task["status"] == "in_progress"
    assert task["version"] == 1


@pytest.mark.asyncio
async def test_stale_read_error_on_version_conflict(conn, task_uuid):
    # First patch succeeds, bumps to version=1
    await patch_task_fields(conn, task_uuid, {"status": "in_progress"})
    # Second patch with expected_version=0 should raise StaleReadError
    with pytest.raises(StaleReadError) as exc_info:
        await patch_task_fields(conn, task_uuid, {"status": "done"}, expected_version=0)
    assert exc_info.value.args[0] == 1  # current_version is 1


@pytest.mark.asyncio
async def test_patch_task_with_correct_version(conn, task_uuid):
    await patch_task_fields(conn, task_uuid, {"status": "in_progress"})
    # Now patch with the correct expected version
    await patch_task_fields(conn, task_uuid, {"status": "done"}, expected_version=1)
    task = await get_task_by_uuid(conn, task_uuid)
    assert task["status"] == "done"
    assert task["version"] == 2


@pytest.mark.asyncio
async def test_delete_task(conn, task_uuid):
    await delete_task_by_uuid(conn, task_uuid)
    task = await get_task_by_uuid(conn, task_uuid)
    assert task is None


@pytest.mark.asyncio
async def test_search_tasks(conn, anchor_id):
    await upsert_plan(conn, DATE)
    tid = str(uuid.uuid4())
    await upsert_tasks(conn, DATE, anchor_id, [{"uuid": tid, "text": "searchable unique xyz", "status": "pending", "position": 0}])
    results = await search_tasks(conn, "searchable unique xyz")
    assert any(r["uuid"] == tid for r in results)


@pytest.mark.asyncio
async def test_task_dependencies(conn, anchor_id):
    await upsert_plan(conn, DATE)
    tid1, tid2 = str(uuid.uuid4()), str(uuid.uuid4())
    await upsert_tasks(conn, DATE, anchor_id, [
        {"uuid": tid1, "text": "Blocker", "status": "pending", "position": 0},
        {"uuid": tid2, "text": "Blocked", "status": "pending", "position": 1},
    ])
    await add_task_dependency(conn, tid2, tid1)
    deps = await get_full_task_dependencies(conn, tid2)
    assert any(d["blocked_by_id"] == tid1 for d in deps)
    await remove_task_dependency(conn, tid2, tid1)
    deps = await get_full_task_dependencies(conn, tid2)
    assert not any(d["blocked_by_id"] == tid1 for d in deps)


@pytest.mark.asyncio
async def test_subtasks(conn, task_uuid):
    sid = await create_subtask(conn, task_uuid, "Do the thing", 0)
    subtasks = await get_subtasks(conn, task_uuid)
    assert any(s["id"] == sid for s in subtasks)
    await update_subtask(conn, sid, done=True)
    subtasks = await get_subtasks(conn, task_uuid)
    done = next(s for s in subtasks if s["id"] == sid)
    assert done["done"] is True
    await delete_subtask(conn, sid)
    subtasks = await get_subtasks(conn, task_uuid)
    assert not any(s["id"] == sid for s in subtasks)
