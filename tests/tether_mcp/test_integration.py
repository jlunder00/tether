"""End-to-end integration test exercising all 9 MCP tools together."""
import pytest
import os
from pathlib import Path
from db.schema import init_db
from db.queries import upsert_anchor, upsert_plan


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    upsert_anchor(path, {"id": "grind_am", "name": "Grind", "time": "09:00",
                          "duration_minutes": 60, "flexibility": "locked",
                          "strictness": 4, "color": "#e05c5c", "position": 0})
    upsert_plan(path, "2026-04-15")
    return path


@pytest.fixture(autouse=True)
def set_db_env(db_path):
    os.environ["TETHER_DB_PATH"] = str(db_path)
    yield
    del os.environ["TETHER_DB_PATH"]


def test_full_workflow():
    """Create context tree → create tasks → read back → patch → delete."""
    from tether_mcp.server import (
        upsert_context, upsert_tasks, read_context, read_tasks,
        delete_tasks, delete_context, get_plan, get_anchors, search,
    )

    # 1. Create context tree with named section files
    ctx_result = upsert_context([{
        "name": "TestProject/Phase1",
        "node_type": "milestone",
        "description": "First phase",
        "sections": {
            "details": {
                "main": "Phase 1 overview\nLine two",
                "plan": "Implementation plan here"
            }
        }
    }])
    assert any(r["action"] == "created" for r in ctx_result)
    phase1_id = next(r["id"] for r in ctx_result if r["name"] == "Phase1")

    # 2. Read back with sections in cat-n format
    nodes = read_context(paths=["TestProject/Phase1"], include_sections=True)
    assert nodes[0] is not None
    assert nodes[0]["name"] == "Phase1"
    details = nodes[0]["sections"]["details"]
    main_section = next(f for f in details if f["name"] == "main")
    assert main_section["body"].startswith("1\t")
    assert main_section["line_count"] == 2

    # 3. Patch a section with find-and-replace
    upsert_context([{
        "name": "TestProject/Phase1",
        "sections": {
            "details": {
                "main": {"mode": "patch", "operations": [
                    {"find": "Phase 1 overview", "replace": "Phase 1 COMPLETE"}
                ]}
            }
        }
    }])
    nodes2 = read_context(paths=["TestProject/Phase1"], include_sections=True)
    main2 = next(f for f in nodes2[0]["sections"]["details"] if f["name"] == "main")
    assert "COMPLETE" in main2["body"]

    # 4. Append to section
    upsert_context([{
        "name": "TestProject/Phase1",
        "sections": {
            "details": {
                "main": {"mode": "append", "value": "Appended line three"}
            }
        }
    }])
    nodes3 = read_context(paths=["TestProject/Phase1"], include_sections=True)
    main3 = next(f for f in nodes3[0]["sections"]["details"] if f["name"] == "main")
    assert main3["line_count"] == 3

    # 5. Create tasks linked to the node
    task_result = upsert_tasks([
        {"text": "Task A", "node_ids": [phase1_id]},
        {"text": "Task B", "status": "in_progress"},
    ])
    assert len(task_result) == 2
    task_a_id = task_result[0]["id"]
    task_b_id = task_result[1]["id"]

    # 6. Add dependency + subtask via upsert
    upsert_tasks([{
        "task_uuid": task_b_id,
        "blocked_by": [task_a_id],
        "subtasks": [{"text": "Sub B1"}],
    }])

    # 7. Read tasks with expansion
    tasks = read_tasks(task_ids=[task_b_id], include_deps=True, include_subtasks=True)
    assert tasks[0]["deps"]["blocked_by"][0]["entity_id"] == task_a_id
    assert tasks[0]["subtasks"][0]["text"] == "Sub B1"

    # 8. Read context with tasks
    nodes_with_tasks = read_context(paths=["TestProject/Phase1"], include_tasks=True)
    assert any(t["id"] == task_a_id for t in nodes_with_tasks[0]["tasks"])

    # 9. Read roots (no params)
    roots = read_context()
    assert any(n["name"] == "TestProject" for n in roots)

    # 10. Search
    results = search("Task A")
    assert any(r["label"] == "Task A" for r in results)

    # 11. Get plan
    plan = get_plan("2026-04-15")
    assert "anchors" in plan

    # 12. Get anchors
    anchors_resp = get_anchors()
    assert "anchors" in anchors_resp
    assert "current" in anchors_resp
    assert any(a["id"] == "grind_am" for a in anchors_resp["anchors"])

    # 13. Delete subtasks only
    delete_tasks([{"task_uuid": task_b_id, "clear_subtasks": True}])
    tasks2 = read_tasks(task_ids=[task_b_id], include_subtasks=True)
    assert tasks2[0]["subtasks"] == []

    # 14. Delete a section file
    delete_context([{
        "path": "TestProject/Phase1",
        "delete_files": [{"section_type": "details", "name": "plan"}]
    }])
    nodes4 = read_context(paths=["TestProject/Phase1"], include_sections=True)
    file_names = [f["name"] for f in nodes4[0]["sections"].get("details", [])]
    assert "plan" not in file_names
    assert "main" in file_names

    # 15. Full delete task
    delete_tasks([{"task_uuid": task_a_id, "delete": True}])
    deleted = read_tasks(task_ids=[task_a_id])
    assert deleted[0] is None  # returns None for missing

    # 16. Full delete context tree
    delete_context([{"path": "TestProject", "delete": True}])
    gone = read_context(paths=["TestProject"])
    assert gone[0] is None
