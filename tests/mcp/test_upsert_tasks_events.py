"""Tests for event scheduling fields in execute_upsert_tasks."""
import contextlib

import pytest
from unittest.mock import AsyncMock, patch

PATCH_TARGETS = [
    "tether_mcp.tools.upsert_tasks.get_task_by_uuid",
    "tether_mcp.tools.upsert_tasks.patch_task_fields",
    "tether_mcp.tools.upsert_tasks.upsert_plan",
    "tether_mcp.tools.upsert_tasks.move_task_atomic",
    "tether_mcp.tools.upsert_tasks.create_unscheduled_task",
    "tether_mcp.tools.upsert_tasks.link_task_to_node",
    "tether_mcp.tools.upsert_tasks.unlink_task_from_node",
    "tether_mcp.tools.upsert_tasks.link_milestone_task",
    "tether_mcp.tools.upsert_tasks.add_dependency",
    "tether_mcp.tools.upsert_tasks.remove_dependency",
    "tether_mcp.tools.upsert_tasks.get_dependencies_for",
    "tether_mcp.tools.upsert_tasks.get_node_by_path",
    "tether_mcp.tools.upsert_tasks.create_subtask",
    "tether_mcp.tools.upsert_tasks.update_subtask",
    "tether_mcp.tools.upsert_tasks.delete_subtask",
    "tether_mcp.tools.upsert_tasks.get_subtasks",
    "tether_mcp.tools.upsert_tasks.promote_task_to_event",
    "tether_mcp.tools.upsert_tasks.update_event_time",
]


def make_mocks():
    return {target.split(".")[-1]: AsyncMock() for target in PATCH_TARGETS}


@pytest.fixture
def conn():
    return AsyncMock()


@pytest.fixture
def mocks():
    return make_mocks()


async def run_upsert(conn, tasks, mocks):
    with contextlib.ExitStack() as stack:
        for t in PATCH_TARGETS:
            stack.enter_context(patch(t, mocks[t.split(".")[-1]]))
        from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
        return await execute_upsert_tasks(conn, tasks)


@pytest.mark.asyncio
async def test_create_task_with_event_times_promotes(conn, mocks):
    mocks["create_unscheduled_task"].return_value = {"id": "task-1"}
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }
    mocks["promote_task_to_event"].return_value = {"id": "task-1"}

    await run_upsert(conn, [{
        "text": "Meeting",
        "start_time": "2026-04-27T09:00:00",
        "end_time": "2026-04-27T10:00:00",
    }], mocks)

    mocks["promote_task_to_event"].assert_called_once_with(
        conn, "task-1", "2026-04-27T09:00:00", "2026-04-27T10:00:00"
    )


@pytest.mark.asyncio
async def test_update_task_with_event_times_calls_update_event_time(conn, mocks):
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }
    mocks["update_event_time"].return_value = {"id": "task-1"}

    await run_upsert(conn, [{
        "task_uuid": "task-1",
        "start_time": "2026-04-27T10:00:00",
        "end_time": "2026-04-27T11:00:00",
    }], mocks)

    mocks["update_event_time"].assert_called_once_with(
        conn, "task-1", "2026-04-27T10:00:00", "2026-04-27T11:00:00"
    )


@pytest.mark.asyncio
async def test_rrule_field_patched_on_task(conn, mocks):
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    await run_upsert(conn, [{
        "task_uuid": "task-1",
        "rrule": "FREQ=WEEKLY;BYDAY=MO",
    }], mocks)

    calls = mocks["patch_task_fields"].call_args_list
    rrule_call = next((c for c in calls if "rrule" in c.args[2]), None)
    assert rrule_call is not None
    assert rrule_call.args[2]["rrule"] == "FREQ=WEEKLY;BYDAY=MO"


@pytest.mark.asyncio
async def test_color_field_patched_on_task(conn, mocks):
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    await run_upsert(conn, [{
        "task_uuid": "task-1",
        "color": "#ff0000",
    }], mocks)

    calls = mocks["patch_task_fields"].call_args_list
    color_call = next((c for c in calls if "color" in c.args[2]), None)
    assert color_call is not None
    assert color_call.args[2]["color"] == "#ff0000"


@pytest.mark.asyncio
async def test_start_without_end_raises(conn, mocks):
    mocks["create_unscheduled_task"].return_value = {"id": "task-1"}

    with pytest.raises(ValueError, match="end_time"):
        await run_upsert(conn, [{"text": "Meeting", "start_time": "2026-04-27T09:00:00"}], mocks)


@pytest.mark.asyncio
async def test_end_without_start_raises(conn, mocks):
    mocks["create_unscheduled_task"].return_value = {"id": "task-1"}

    with pytest.raises(ValueError, match="start_time"):
        await run_upsert(conn, [{"text": "Meeting", "end_time": "2026-04-27T10:00:00"}], mocks)


@pytest.mark.asyncio
async def test_no_event_times_does_not_call_promote(conn, mocks):
    mocks["create_unscheduled_task"].return_value = {"id": "task-1"}
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Plain task", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    await run_upsert(conn, [{"text": "Plain task"}], mocks)

    mocks["promote_task_to_event"].assert_not_called()
