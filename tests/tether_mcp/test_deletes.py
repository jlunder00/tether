"""Tests for delete_tasks and delete_context tools (Task 7 of MCP Interface Consolidation)."""
import os
import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import (
    create_node,
    get_node,
    get_node_by_path,
    get_task_by_uuid,
    create_unscheduled_task,
    get_subtasks,
    create_subtask,
    link_task_to_node,
    get_node_tasks,
    add_dependency,
    get_dependencies_for,
    upsert_section,
    list_section_files,
    get_section,
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


# ---------------------------------------------------------------------------
# delete_tasks tests
# ---------------------------------------------------------------------------

# 1. Delete entire task → gone from DB
def test_delete_task_entire(db_path):
    from tether_mcp.tools.delete_tasks import execute_delete_tasks
    task = create_unscheduled_task(db_path, "Task to delete")
    task_uuid = task["id"]

    results = execute_delete_tasks([{"task_uuid": task_uuid, "delete": True}])

    assert len(results) == 1
    assert results[0]["action"] == "deleted"
    assert results[0]["task_uuid"] == task_uuid
    assert get_task_by_uuid(db_path, task_uuid) is None


# 2. clear_subtasks → subtasks removed, task still exists
def test_clear_subtasks(db_path):
    from tether_mcp.tools.delete_tasks import execute_delete_tasks
    task = create_unscheduled_task(db_path, "Task with subtasks")
    sub1 = create_subtask(db_path, task["id"], "Subtask one", position=0)
    sub2 = create_subtask(db_path, task["id"], "Subtask two", position=1)

    results = execute_delete_tasks([{"task_uuid": task["id"], "clear_subtasks": True}])

    assert results[0]["action"] == "cleared"
    assert "subtasks" in results[0]["cleared"]
    # Task still exists
    assert get_task_by_uuid(db_path, task["id"]) is not None
    # Subtasks gone
    assert get_subtasks(db_path, task["id"]) == []


# 3. clear_description → description is None, task exists
def test_clear_description(db_path):
    from tether_mcp.tools.delete_tasks import execute_delete_tasks
    task = create_unscheduled_task(db_path, "Described task", description="Some details")
    assert get_task_by_uuid(db_path, task["id"])["description"] == "Some details"

    results = execute_delete_tasks([{"task_uuid": task["id"], "clear_description": True}])

    assert results[0]["action"] == "cleared"
    assert "description" in results[0]["cleared"]
    updated = get_task_by_uuid(db_path, task["id"])
    assert updated is not None
    assert updated["description"] is None


# 4. clear_deps → dependencies removed
def test_clear_deps(db_path):
    from tether_mcp.tools.delete_tasks import execute_delete_tasks
    blocker = create_unscheduled_task(db_path, "Blocker")
    blocked = create_unscheduled_task(db_path, "Blocked")
    add_dependency(db_path, "task", blocker["id"], "task", blocked["id"])

    # Confirm dependency exists
    deps = get_dependencies_for(db_path, "task", blocked["id"])
    assert len(deps["blocked_by"]) == 1

    results = execute_delete_tasks([{"task_uuid": blocked["id"], "clear_deps": True}])

    assert results[0]["action"] == "cleared"
    assert "deps" in results[0]["cleared"]
    deps_after = get_dependencies_for(db_path, "task", blocked["id"])
    assert deps_after["blocked_by"] == []
    assert deps_after["blocks"] == []


# ---------------------------------------------------------------------------
# delete_context tests
# ---------------------------------------------------------------------------

# 5. Delete entire node → gone from DB
def test_delete_node_entire(db_path):
    from tether_mcp.tools.delete_context import execute_delete_context
    node = create_node(db_path, parent_id=None, name="DeleteMe")

    results = execute_delete_context([{"node_id": node["id"], "delete": True}])

    assert len(results) == 1
    assert results[0]["action"] == "deleted"
    assert results[0]["node_id"] == node["id"]
    assert get_node(db_path, node["id"]) is None


# 6. Archive node → archived=1
def test_archive_node(db_path):
    from tether_mcp.tools.delete_context import execute_delete_context
    node = create_node(db_path, parent_id=None, name="ArchiveMe")
    assert get_node(db_path, node["id"])["archived"] == 0

    results = execute_delete_context([{"node_id": node["id"], "archive": True}])

    assert results[0]["action"] == "archived"
    updated = get_node(db_path, node["id"])
    assert updated is not None
    assert updated["archived"] == 1


# 7. Delete by path → works same as by node_id
def test_delete_by_path(db_path):
    from tether_mcp.tools.delete_context import execute_delete_context
    node = create_node(db_path, parent_id=None, name="PathNode")
    node_id = node["id"]

    results = execute_delete_context([{"path": "PathNode", "delete": True}])

    assert results[0]["action"] == "deleted"
    assert results[0]["node_id"] == node_id
    assert get_node(db_path, node_id) is None


# 8. delete_files → specific file removed, others remain
def test_delete_specific_file(db_path):
    from tether_mcp.tools.delete_context import execute_delete_context
    node = create_node(db_path, parent_id=None, name="SectionNode")
    upsert_section(db_path, node["id"], "notes", "Keep this", name="keeper")
    upsert_section(db_path, node["id"], "notes", "Delete this", name="goner")

    results = execute_delete_context([{
        "node_id": node["id"],
        "delete_files": [{"section_type": "notes", "name": "goner"}],
    }])

    assert results[0]["action"] == "cleared"
    assert "file:notes/goner" in results[0]["cleared"]
    # "goner" deleted
    assert get_section(db_path, node["id"], "notes", name="goner") is None
    # "keeper" still present
    assert get_section(db_path, node["id"], "notes", name="keeper") is not None


# 9. clear_sections → all files in that section_type removed
def test_clear_sections(db_path):
    from tether_mcp.tools.delete_context import execute_delete_context
    node = create_node(db_path, parent_id=None, name="MultiSection")
    upsert_section(db_path, node["id"], "notes", "Note one", name="n1")
    upsert_section(db_path, node["id"], "notes", "Note two", name="n2")
    upsert_section(db_path, node["id"], "log", "Log entry", name="main")

    results = execute_delete_context([{
        "node_id": node["id"],
        "clear_sections": ["notes"],
    }])

    assert results[0]["action"] == "cleared"
    assert "section:notes" in results[0]["cleared"]
    # notes section cleared
    assert list_section_files(db_path, node["id"], "notes") == []
    # log section untouched
    assert list_section_files(db_path, node["id"], "log") != []
