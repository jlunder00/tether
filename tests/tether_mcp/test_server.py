import pytest
import os
from pathlib import Path
from db.schema import init_db
from db.queries import upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_anchor(path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                          "duration_minutes": 120, "flexibility": "locked",
                          "strictness": 4, "color": "#e05c5c", "position": 0})
    upsert_anchor(path, {"id": "deep_work", "name": "Deep Work", "time": "10:30",
                          "duration_minutes": 120, "flexibility": "flexible",
                          "strictness": 2, "color": "#7c6af7", "position": 1})
    upsert_plan(path, "2026-03-26")
    upsert_tasks(path, "2026-03-26", "grind_am", tasks=["Apply to 3 jobs"], notes="ML roles")
    upsert_context_entry(path, "Job Applications", "ML engineer roles.")
    upsert_context_entry(path, "5D Multiverse", "Game engine — flex time only.")
    upsert_context_entry(path, "Intellipat", "Patent startup.")
    upsert_context_entry(path, "Intellipat/Backend", "Backend services.")
    upsert_context_entry(path, "Intellipat/Frontend", "React frontend.")
    return path


@pytest.fixture(autouse=True)
def set_db_env(db_path):
    os.environ["TETHER_DB_PATH"] = str(db_path)
    yield
    del os.environ["TETHER_DB_PATH"]


def test_get_today_plan_returns_anchors():
    from tether_mcp.server import _get_today_plan
    plan = _get_today_plan("2026-03-26")
    assert "grind_am" in plan["anchors"]
    assert [t["text"] for t in plan["anchors"]["grind_am"]["tasks"]] == ["Apply to 3 jobs"]


def test_update_plan_tasks_persists(db_path):
    from tether_mcp.server import _update_plan_tasks
    from db.queries import get_plan
    _update_plan_tasks("grind_am", ["New task A", "New task B"], "2026-03-26")
    plan = get_plan(db_path, "2026-03-26")
    texts = [t["text"] for t in plan["anchors"]["grind_am"]["tasks"]]
    # upsert_tasks no longer deletes — old tasks are preserved, new ones added
    assert "New task A" in texts
    assert "New task B" in texts


def test_get_anchors_returns_list():
    from tether_mcp.server import _get_anchors
    anchors = _get_anchors()
    ids = [a["id"] for a in anchors]
    assert "grind_am" in ids
    assert "deep_work" in ids


def test_get_current_anchor_returns_dict():
    from tether_mcp.server import _get_current_anchor
    anchor = _get_current_anchor()
    assert "id" in anchor
    assert "name" in anchor


# --- upsert_task unified tool ---

def test_upsert_task_create_backlog(db_path):
    from tether_mcp.server import upsert_task
    result = upsert_task(text="Backlog item", description="Details here",
                         context_subject="Intellipat")
    assert result["id"]
    assert result["text"] == "Backlog item"
    assert result["description"] == "Details here"
    # Verify context_subject set directly on task
    from db.queries import get_task_by_uuid
    task = get_task_by_uuid(db_path, result["id"])
    assert task["context_subject"] == "Intellipat"


def test_upsert_task_create_scheduled(db_path):
    from tether_mcp.server import upsert_task
    result = upsert_task(text="Scheduled task", date="2026-03-26", anchor_id="grind_am")
    assert result["id"]
    assert result["plan_date"] == "2026-03-26"
    assert result["anchor_id"] == "grind_am"


def test_upsert_task_create_with_milestone(db_path):
    from tether_mcp.server import upsert_task
    from db.queries import create_milestone
    m = create_milestone(db_path, "Intellipat", "Test MS")
    result = upsert_task(text="Linked task", milestone_ids=[m["id"]],
                         context_subject="Intellipat")
    assert result["id"]
    from db.queries import get_milestones
    ms = get_milestones(db_path, "Intellipat")
    test_ms = next(x for x in ms if x["id"] == m["id"])
    assert result["id"] in test_ms["task_ids"]


def test_upsert_task_update_existing(db_path):
    from tether_mcp.server import upsert_task
    created = upsert_task(text="Original")
    updated = upsert_task(task_uuid=created["id"], status="done",
                          description="Now done")
    assert updated["status"] == "done"
    assert updated["description"] == "Now done"
    assert updated["text"] == "Original"


def test_upsert_task_move_to_backlog(db_path):
    from tether_mcp.server import upsert_task
    created = upsert_task(text="Will unschedule", date="2026-03-26", anchor_id="grind_am")
    assert created["plan_date"] == "2026-03-26"
    moved = upsert_task(task_uuid=created["id"], backlog=True)
    assert moved["plan_date"] is None
    assert moved["anchor_id"] is None
