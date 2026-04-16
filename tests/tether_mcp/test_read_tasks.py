"""Tests for the read_tasks tool (Task 4 of MCP Interface Consolidation)."""
import os
import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import (
    upsert_anchor,
    upsert_plan,
    upsert_tasks,
    create_unscheduled_task,
    add_dependency,
    create_subtask,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture(autouse=True)
def set_db_env(db_path):
    os.environ["TETHER_DB_PATH"] = str(db_path)
    yield
    del os.environ["TETHER_DB_PATH"]


@pytest.fixture
def sample_data(db_path):
    """Create an anchor, plan, and two scheduled tasks plus one unscheduled task."""
    upsert_anchor(db_path, {
        "id": "grind_am",
        "name": "Grind AM",
        "time": "09:00",
        "duration_minutes": 120,
        "flexibility": "flexible",
        "strictness": 3,
        "color": "#5b8dee",
        "position": 0,
        "followup_config": None,
    })
    upsert_plan(db_path, "2026-04-15")

    tasks = upsert_tasks(db_path, "2026-04-15", "grind_am", [
        {"text": "Write MCP tool", "status": "pending", "context_subject": "Tether"},
        {"text": "Review PR", "status": "done", "context_subject": "Tether"},
    ])

    # Unscheduled / backlog task
    backlog = create_unscheduled_task(
        db_path, "Backlog item", status="pending", context_subject="Backlog"
    )

    return {
        "pending_task": tasks[0],
        "done_task": tasks[1],
        "backlog_task": backlog,
    }


# ---------------------------------------------------------------------------
# 1. No filters → returns all tasks (≥2)
# ---------------------------------------------------------------------------

def test_no_filters_returns_all_tasks(sample_data):
    from tether_mcp.tools.read_tasks import execute_read_tasks
    result = execute_read_tasks()
    assert result is not None
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# 2. Filter by status="done" → only done tasks
# ---------------------------------------------------------------------------

def test_filter_by_status_done(sample_data):
    from tether_mcp.tools.read_tasks import execute_read_tasks
    result = execute_read_tasks(status="done")
    assert len(result) >= 1
    for task in result:
        assert task["status"] == "done"


# ---------------------------------------------------------------------------
# 3. Filter by context="Tether" → only matching context
# ---------------------------------------------------------------------------

def test_filter_by_context(sample_data):
    from tether_mcp.tools.read_tasks import execute_read_tasks
    result = execute_read_tasks(context="Tether")
    assert len(result) >= 1
    for task in result:
        assert task["context_subject"] == "Tether"


# ---------------------------------------------------------------------------
# 4. Filter by date="2026-04-15" → only that date
# ---------------------------------------------------------------------------

def test_filter_by_date(sample_data):
    from tether_mcp.tools.read_tasks import execute_read_tasks
    result = execute_read_tasks(date="2026-04-15")
    assert len(result) >= 1
    for task in result:
        assert task["plan_date"] == "2026-04-15"


# ---------------------------------------------------------------------------
# 5. Filter unscheduled=True → only plan_date=None
# ---------------------------------------------------------------------------

def test_filter_unscheduled(sample_data):
    from tether_mcp.tools.read_tasks import execute_read_tasks
    result = execute_read_tasks(unscheduled=True)
    assert len(result) >= 1
    for task in result:
        assert task["plan_date"] is None


# ---------------------------------------------------------------------------
# 6. By task_ids → returns only those tasks
# ---------------------------------------------------------------------------

def test_by_task_ids(sample_data):
    from tether_mcp.tools.read_tasks import execute_read_tasks
    tid = sample_data["pending_task"]["id"]
    result = execute_read_tasks(task_ids=[tid])
    assert len(result) == 1
    assert result[0]["id"] == tid


# ---------------------------------------------------------------------------
# 7. include_deps=True → "deps" key present with blocks/blocked_by
# ---------------------------------------------------------------------------

def test_include_deps(sample_data, db_path):
    from tether_mcp.tools.read_tasks import execute_read_tasks
    tid = sample_data["pending_task"]["id"]
    result = execute_read_tasks(task_ids=[tid], include_deps=True)
    assert len(result) == 1
    task = result[0]
    assert "deps" in task
    assert "blocks" in task["deps"]
    assert "blocked_by" in task["deps"]


# ---------------------------------------------------------------------------
# 8. include_subtasks=True → "subtasks" key present
# ---------------------------------------------------------------------------

def test_include_subtasks(sample_data, db_path):
    from tether_mcp.tools.read_tasks import execute_read_tasks
    tid = sample_data["pending_task"]["id"]
    create_subtask(db_path, tid, "Subtask one", position=0)
    result = execute_read_tasks(task_ids=[tid], include_subtasks=True)
    assert len(result) == 1
    task = result[0]
    assert "subtasks" in task
    assert len(task["subtasks"]) >= 1
    assert task["subtasks"][0]["text"] == "Subtask one"


# ---------------------------------------------------------------------------
# 9. Without include flags → no "deps" or "subtasks" keys
# ---------------------------------------------------------------------------

def test_no_include_flags_no_extra_keys(sample_data):
    from tether_mcp.tools.read_tasks import execute_read_tasks
    result = execute_read_tasks()
    assert len(result) >= 1
    for task in result:
        assert "deps" not in task
        assert "subtasks" not in task
