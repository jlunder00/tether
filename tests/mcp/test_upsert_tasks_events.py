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


def _patch_dict_for(call):
    """Pull the fields dict out of a patch_task_fields call, positional or kw."""
    if len(call.args) > 2:
        return call.args[2]
    return call.kwargs.get("patch") or call.kwargs.get("fields") or {}


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
async def test_update_task_with_event_times_uses_patch_task_fields(conn, mocks):
    """MCP update of start/end times goes through patch_task_fields (trusted path).

    update_event_time now enforces a recurrence-aware delta for calendar UI moves
    and raises ValueError for recurring events without original_start_time.  The
    MCP tool is an administrative path that sets times directly, so it uses
    patch_task_fields to avoid that guard.
    """
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    await run_upsert(conn, [{
        "task_uuid": "task-1",
        "start_time": "2026-04-27T10:00:00",
        "end_time": "2026-04-27T11:00:00",
    }], mocks)

    # Time fields must flow through patch_task_fields, not update_event_time
    mocks["update_event_time"].assert_not_called()
    calls = mocks["patch_task_fields"].call_args_list
    time_call = next((c for c in calls if "start_time" in _patch_dict_for(c)), None)
    assert time_call is not None, "start_time/end_time should be passed to patch_task_fields"
    patch_dict = _patch_dict_for(time_call)
    assert patch_dict["start_time"] == "2026-04-27T10:00:00"
    assert patch_dict["end_time"] == "2026-04-27T11:00:00"


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
    rrule_call = next((c for c in calls if "rrule" in _patch_dict_for(c)), None)
    assert rrule_call is not None
    assert _patch_dict_for(rrule_call)["rrule"] == "FREQ=WEEKLY;BYDAY=MO"


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
    color_call = next((c for c in calls if "color" in _patch_dict_for(c)), None)
    assert color_call is not None
    assert _patch_dict_for(color_call)["color"] == "#ff0000"


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


@pytest.mark.asyncio
async def test_start_after_end_raises(conn, mocks):
    """start_time must be strictly before end_time."""
    mocks["create_unscheduled_task"].return_value = {"id": "task-1"}

    with pytest.raises(ValueError, match="before end_time"):
        await run_upsert(conn, [{
            "text": "Bad meeting",
            "start_time": "2026-04-27T11:00:00",
            "end_time": "2026-04-27T10:00:00",
        }], mocks)


@pytest.mark.asyncio
async def test_start_equal_end_raises(conn, mocks):
    """Zero-length events are rejected."""
    mocks["create_unscheduled_task"].return_value = {"id": "task-1"}

    with pytest.raises(ValueError, match="before end_time"):
        await run_upsert(conn, [{
            "text": "Zero meeting",
            "start_time": "2026-04-27T10:00:00",
            "end_time": "2026-04-27T10:00:00",
        }], mocks)


@pytest.mark.asyncio
async def test_update_start_without_end_raises(conn, mocks):
    """Validation fires on the UPDATE path too."""
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    with pytest.raises(ValueError, match="end_time"):
        await run_upsert(conn, [{
            "task_uuid": "task-1",
            "start_time": "2026-04-27T09:00:00",
        }], mocks)


@pytest.mark.asyncio
async def test_update_rrule_none_clears(conn, mocks):
    """Explicit rrule=None on update should be patched (to clear the field)."""
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    await run_upsert(conn, [{
        "task_uuid": "task-1",
        "rrule": None,
    }], mocks)

    calls = mocks["patch_task_fields"].call_args_list
    rrule_call = next((c for c in calls if "rrule" in _patch_dict_for(c)), None)
    assert rrule_call is not None
    assert _patch_dict_for(rrule_call)["rrule"] is None


@pytest.mark.asyncio
async def test_update_color_none_clears(conn, mocks):
    """Explicit color=None on update should be patched (to clear the field)."""
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    await run_upsert(conn, [{
        "task_uuid": "task-1",
        "color": None,
    }], mocks)

    calls = mocks["patch_task_fields"].call_args_list
    color_call = next((c for c in calls if "color" in _patch_dict_for(c)), None)
    assert color_call is not None
    assert _patch_dict_for(color_call)["color"] is None


@pytest.mark.asyncio
async def test_create_with_rrule_patches(conn, mocks):
    """rrule on a new task should be patched after create."""
    mocks["create_unscheduled_task"].return_value = {"id": "task-1"}
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    await run_upsert(conn, [{
        "text": "Meeting",
        "rrule": "FREQ=DAILY",
    }], mocks)

    calls = mocks["patch_task_fields"].call_args_list
    rrule_call = next((c for c in calls if "rrule" in _patch_dict_for(c)), None)
    assert rrule_call is not None
    assert _patch_dict_for(rrule_call)["rrule"] == "FREQ=DAILY"


@pytest.mark.asyncio
async def test_create_with_color_patches(conn, mocks):
    """color on a new task should be patched after create."""
    mocks["create_unscheduled_task"].return_value = {"id": "task-1"}
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    await run_upsert(conn, [{
        "text": "Meeting",
        "color": "#00ff00",
    }], mocks)

    calls = mocks["patch_task_fields"].call_args_list
    color_call = next((c for c in calls if "color" in _patch_dict_for(c)), None)
    assert color_call is not None
    assert _patch_dict_for(color_call)["color"] == "#00ff00"


@pytest.mark.asyncio
async def test_create_with_rrule_none_does_not_patch(conn, mocks):
    """rrule=None on CREATE is a no-op (no need to clear a brand-new field)."""
    mocks["create_unscheduled_task"].return_value = {"id": "task-1"}
    mocks["get_task_by_uuid"].return_value = {
        "id": "task-1", "text": "Meeting", "status": "pending",
        "description": None, "context_subject": None, "plan_date": None, "anchor_id": None,
    }

    await run_upsert(conn, [{
        "text": "Meeting",
        "rrule": None,
    }], mocks)

    calls = mocks["patch_task_fields"].call_args_list
    assert not any("rrule" in _patch_dict_for(c) for c in calls)
