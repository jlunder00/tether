"""Tests for db/pg_queries/tasks.py — including version-conflict (StaleReadError)."""
import pytest
import uuid

from tests.db.pg_conftest import conn, TEST_USER_ID  # noqa: F401
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
    await seed_default_anchors(conn)
    from db.pg_queries.anchors import get_anchors
    anchors = await get_anchors(conn)
    return anchors[0]["id"]


@pytest.fixture
async def task_uuid(conn, anchor_id):
    await upsert_plan(conn, DATE)
    tasks = await upsert_tasks(conn, DATE, anchor_id, [{"text": "Test task", "status": "pending"}])
    return tasks[0]["id"]


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
    tasks = await upsert_tasks(conn, DATE, anchor_id, [{"text": "searchable unique xyz", "status": "pending"}])
    tid = tasks[0]["id"]
    results = await search_tasks(conn, "searchable unique xyz")
    assert any(r["id"] == tid for r in results)


@pytest.mark.asyncio
async def test_task_dependencies(conn, anchor_id):
    await upsert_plan(conn, DATE)
    tasks = await upsert_tasks(conn, DATE, anchor_id, [
        {"text": "Blocker", "status": "pending"},
        {"text": "Blocked", "status": "pending"},
    ])
    tid1, tid2 = tasks[0]["id"], tasks[1]["id"]
    await add_task_dependency(conn, tid2, tid1)
    deps = await get_full_task_dependencies(conn, tid2)
    assert any(d["blocked_by_id"] == tid1 for d in deps)
    await remove_task_dependency(conn, tid2, tid1)
    deps = await get_full_task_dependencies(conn, tid2)
    assert not any(d["blocked_by_id"] == tid1 for d in deps)


@pytest.mark.asyncio
async def test_subtasks(conn, task_uuid):
    subtask = await create_subtask(conn, task_uuid, "Do the thing", 0)
    sid = subtask["id"]
    subtasks = await get_subtasks(conn, task_uuid)
    assert any(s["id"] == sid for s in subtasks)
    await update_subtask(conn, sid, done=True)
    subtasks = await get_subtasks(conn, task_uuid)
    done = next(s for s in subtasks if s["id"] == sid)
    assert done["done"] is True
    await delete_subtask(conn, sid)
    subtasks = await get_subtasks(conn, task_uuid)
    assert not any(s["id"] == sid for s in subtasks)


# ─── patch_task_fields: start_time / end_time null passthrough ────────────────

@pytest.fixture
async def event_task_uuid(conn, anchor_id):
    """A task that has already been promoted to an event (has start_time/end_time)."""
    await upsert_plan(conn, DATE)
    # Insert directly so we can set start_time/end_time
    row = await conn.fetchrow(
        """
        INSERT INTO tasks (uuid, user_id, text, status, start_time, end_time)
        VALUES (
            gen_random_uuid(),
            current_setting('app.current_user_id', true)::uuid,
            'Promoted event task',
            'pending',
            '2026-05-01T09:00:00Z',
            '2026-05-01T10:00:00Z'
        )
        RETURNING uuid
        """
    )
    return str(row["uuid"])


@pytest.mark.asyncio
async def test_patch_task_fields_sets_start_end_time(conn, event_task_uuid):
    """patch_task_fields can set start_time and end_time to new values."""
    result = await patch_task_fields(conn, event_task_uuid, {
        "start_time": "2026-05-02T14:00:00Z",
        "end_time": "2026-05-02T15:00:00Z",
    })
    # Verify via direct DB read since patch_task_fields SELECT may not return these cols
    row = await conn.fetchrow(
        "SELECT start_time, end_time FROM tasks WHERE uuid = $1::uuid",
        event_task_uuid,
    )
    assert row["start_time"] is not None
    assert "14" in str(row["start_time"]) or "14:00" in str(row["start_time"])


@pytest.mark.asyncio
async def test_patch_task_fields_clears_start_end_time_with_null(conn, event_task_uuid):
    """patch_task_fields with start_time=None and end_time=None demotes event back to task."""
    result = await patch_task_fields(conn, event_task_uuid, {
        "start_time": None,
        "end_time": None,
    })
    row = await conn.fetchrow(
        "SELECT start_time, end_time FROM tasks WHERE uuid = $1::uuid",
        event_task_uuid,
    )
    assert row["start_time"] is None, "start_time should be cleared to NULL"
    assert row["end_time"] is None, "end_time should be cleared to NULL"


@pytest.mark.asyncio
async def test_patch_task_fields_omitting_start_time_does_not_clear_it(conn, event_task_uuid):
    """Omitting start_time from the patch dict must NOT clear the existing value."""
    # Patch only the status — start_time should remain
    await patch_task_fields(conn, event_task_uuid, {"status": "in_progress"})
    row = await conn.fetchrow(
        "SELECT start_time FROM tasks WHERE uuid = $1::uuid",
        event_task_uuid,
    )
    assert row["start_time"] is not None, "start_time must not be cleared when not in patch dict"
