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
    return path


@pytest.fixture(autouse=True)
def set_db_env(db_path):
    os.environ["TETHER_DB_PATH"] = str(db_path)
    yield
    del os.environ["TETHER_DB_PATH"]


def test_list_context_entries_returns_subjects():
    from tether_mcp.server import _list_context_entries
    entries = _list_context_entries()
    subjects = [e["subject"] for e in entries]
    assert "Job Applications" in subjects
    assert "5D Multiverse" in subjects


def test_update_context_entry_persists(db_path):
    from tether_mcp.server import _update_context_entry
    from db.queries import get_context_entries
    _update_context_entry("Job Applications", "Updated body.")
    entries = get_context_entries(db_path)
    match = next(e for e in entries if e["subject"] == "Job Applications")
    assert match["body"] == "Updated body."


def test_get_today_plan_returns_anchors():
    from tether_mcp.server import _get_today_plan
    plan = _get_today_plan("2026-03-26")
    assert "grind_am" in plan["anchors"]
    assert plan["anchors"]["grind_am"]["tasks"] == ["Apply to 3 jobs"]


def test_update_plan_tasks_persists(db_path):
    from tether_mcp.server import _update_plan_tasks
    from db.queries import get_plan
    _update_plan_tasks("grind_am", ["New task A", "New task B"], "2026-03-26")
    plan = get_plan(db_path, "2026-03-26")
    assert plan["anchors"]["grind_am"]["tasks"] == ["New task A", "New task B"]


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
