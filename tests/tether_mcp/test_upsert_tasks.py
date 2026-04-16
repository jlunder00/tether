"""Tests for the upsert_tasks tool (Task 5 of MCP Interface Consolidation)."""
import os
import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import (
    upsert_anchor,
    upsert_plan,
    upsert_tasks,
    create_unscheduled_task,
    get_node_tasks,
    get_subtasks,
    create_subtask,
    create_node,
    add_dependency,
    get_dependencies_for,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    upsert_anchor(path, {
        "id": "grind_am",
        "name": "Grind",
        "time": "09:00",
        "duration_minutes": 60,
        "flexibility": "locked",
        "strictness": 4,
        "color": "#e05c5c",
        "position": 0,
    })
    upsert_plan(path, "2026-04-15")
    return path


@pytest.fixture(autouse=True)
def set_db_env(db_path):
    os.environ["TETHER_DB_PATH"] = str(db_path)
    yield
    del os.environ["TETHER_DB_PATH"]


# ---------------------------------------------------------------------------
# 1. Create single backlog task
# ---------------------------------------------------------------------------

def test_create_backlog_task():
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    results = execute_upsert_tasks([{"text": "Buy milk"}])
    assert len(results) == 1
    task = results[0]
    assert task["id"]
    assert task["text"] == "Buy milk"
    assert task["status"] == "pending"
    assert task["plan_date"] is None


# ---------------------------------------------------------------------------
# 2. Create scheduled task
# ---------------------------------------------------------------------------

def test_create_scheduled_task():
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    results = execute_upsert_tasks([{
        "text": "Morning standup",
        "date": "2026-04-15",
        "anchor_id": "grind_am",
    }])
    assert len(results) == 1
    task = results[0]
    assert task["plan_date"] == "2026-04-15"
    assert task["anchor_id"] == "grind_am"


# ---------------------------------------------------------------------------
# 3. Update status
# ---------------------------------------------------------------------------

def test_update_status(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    task = create_unscheduled_task(db_path, "Do laundry")
    results = execute_upsert_tasks([{
        "task_uuid": task["id"],
        "status": "done",
    }])
    assert len(results) == 1
    assert results[0]["status"] == "done"


# ---------------------------------------------------------------------------
# 4. Description replace (bare string)
# ---------------------------------------------------------------------------

def test_description_replace(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    task = create_unscheduled_task(db_path, "Write docs", description="Old description")
    results = execute_upsert_tasks([{
        "task_uuid": task["id"],
        "description": "New description",
    }])
    assert len(results) == 1
    assert results[0]["description"] == "New description"


# ---------------------------------------------------------------------------
# 5. Description append mode
# ---------------------------------------------------------------------------

def test_description_append(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    task = create_unscheduled_task(db_path, "Write docs", description="Line one")
    results = execute_upsert_tasks([{
        "task_uuid": task["id"],
        "description": {"mode": "append", "value": "Line two"},
    }])
    assert len(results) == 1
    assert results[0]["description"] == "Line one\nLine two"


# ---------------------------------------------------------------------------
# 6. Move to backlog
# ---------------------------------------------------------------------------

def test_move_to_backlog(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    tasks = upsert_tasks(db_path, "2026-04-15", "grind_am", [{"text": "Scheduled task"}])
    scheduled = tasks[0]
    assert scheduled["id"]

    results = execute_upsert_tasks([{
        "task_uuid": scheduled["id"],
        "backlog": True,
    }])
    assert len(results) == 1
    assert results[0]["plan_date"] is None


# ---------------------------------------------------------------------------
# 7. node_ids linking
# ---------------------------------------------------------------------------

def test_node_ids_linking(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    node = create_node(db_path, parent_id=None, name="TestProject")
    task = create_unscheduled_task(db_path, "Node linked task")

    execute_upsert_tasks([{
        "task_uuid": task["id"],
        "node_ids": [node["id"]],
    }])

    linked = get_node_tasks(db_path, node["id"])
    task_ids = [t["id"] for t in linked]
    assert task["id"] in task_ids


# ---------------------------------------------------------------------------
# 8. node_ids_remove
# ---------------------------------------------------------------------------

def test_node_ids_remove(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    from db.queries import link_task_to_node
    node = create_node(db_path, parent_id=None, name="RemoveProject")
    task = create_unscheduled_task(db_path, "Task to unlink")
    link_task_to_node(db_path, node["id"], task["id"])

    # Verify linked
    assert task["id"] in [t["id"] for t in get_node_tasks(db_path, node["id"])]

    execute_upsert_tasks([{
        "task_uuid": task["id"],
        "node_ids_remove": [node["id"]],
    }])

    linked = get_node_tasks(db_path, node["id"])
    assert task["id"] not in [t["id"] for t in linked]


# ---------------------------------------------------------------------------
# 9. blocked_by add + blocked_by_remove
# ---------------------------------------------------------------------------

def test_blocked_by_add_and_remove(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    blocker = create_unscheduled_task(db_path, "Blocker task")
    blocked = create_unscheduled_task(db_path, "Blocked task")

    # Add dependency
    execute_upsert_tasks([{
        "task_uuid": blocked["id"],
        "blocked_by": [blocker["id"]],
    }])

    deps = get_dependencies_for(db_path, "task", blocked["id"])
    assert any(d["entity_id"] == blocker["id"] for d in deps["blocked_by"])

    # Remove dependency
    execute_upsert_tasks([{
        "task_uuid": blocked["id"],
        "blocked_by_remove": [blocker["id"]],
    }])

    deps_after = get_dependencies_for(db_path, "task", blocked["id"])
    assert not any(d["entity_id"] == blocker["id"] for d in deps_after["blocked_by"])


# ---------------------------------------------------------------------------
# 10. Subtask create
# ---------------------------------------------------------------------------

def test_subtask_create(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    task = create_unscheduled_task(db_path, "Parent task")

    execute_upsert_tasks([{
        "task_uuid": task["id"],
        "subtasks": [{"text": "Do step one"}],
    }])

    subs = get_subtasks(db_path, task["id"])
    assert len(subs) == 1
    assert subs[0]["text"] == "Do step one"


# ---------------------------------------------------------------------------
# 11. subtasks_remove
# ---------------------------------------------------------------------------

def test_subtasks_remove(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    task = create_unscheduled_task(db_path, "Parent task")
    sub = create_subtask(db_path, task["id"], "Step to delete", position=0)

    execute_upsert_tasks([{
        "task_uuid": task["id"],
        "subtasks_remove": [sub["id"]],
    }])

    subs = get_subtasks(db_path, task["id"])
    assert not any(s["id"] == sub["id"] for s in subs)


# ---------------------------------------------------------------------------
# 12. Duplicate UUID in batch raises ValueError
# ---------------------------------------------------------------------------

def test_duplicate_uuid_raises(db_path):
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    task = create_unscheduled_task(db_path, "Original task")

    with pytest.raises(ValueError, match="Duplicate task_uuid"):
        execute_upsert_tasks([
            {"task_uuid": task["id"], "status": "done"},
            {"task_uuid": task["id"], "status": "pending"},
        ])
