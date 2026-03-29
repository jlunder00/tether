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


def test_list_context_entries_top_level_only_by_default():
    from tether_mcp.server import _list_context_entries
    entries = _list_context_entries()
    subjects = [e["subject"] for e in entries]
    assert "Job Applications" in subjects
    assert "5D Multiverse" in subjects
    assert "Intellipat" in subjects
    assert "Intellipat/Backend" not in subjects


def test_list_context_entries_has_children_flag():
    from tether_mcp.server import _list_context_entries
    entries = _list_context_entries()
    intellipat = next(e for e in entries if e["subject"] == "Intellipat")
    job_apps = next(e for e in entries if e["subject"] == "Job Applications")
    assert intellipat["has_children"] is True
    assert job_apps["has_children"] is False


def test_list_context_entries_with_prefix():
    from tether_mcp.server import _list_context_entries
    entries = _list_context_entries(prefix="Intellipat")
    subjects = {e["subject"] for e in entries}
    assert subjects == {"Intellipat", "Intellipat/Backend", "Intellipat/Frontend"}


def test_get_context_entry_exact():
    from tether_mcp.server import _get_context_entry
    entry = _get_context_entry("Intellipat/Backend")
    assert entry["subject"] == "Intellipat/Backend"
    assert entry["body"] == "Backend services."


def test_get_context_entry_not_found_raises():
    from tether_mcp.server import _get_context_entry
    with pytest.raises(ValueError, match="No context entry found"):
        _get_context_entry("Nonexistent")


def test_update_context_entry_persists(db_path):
    from tether_mcp.server import _update_context_entry
    from db.queries import get_context_entries
    _update_context_entry("Job Applications", "Updated body.")
    entries = get_context_entries(db_path)
    match = next(e for e in entries if e["subject"] == "Job Applications")
    assert match["body"] == "Updated body."


def test_append_context_entry(db_path):
    from tether_mcp.server import _append_context_entry
    from db.queries import get_context_entries
    _append_context_entry("Job Applications", "New line added.")
    entries = get_context_entries(db_path)
    body = next(e["body"] for e in entries if e["subject"] == "Job Applications")
    assert "ML engineer roles." in body
    assert "New line added." in body


def test_append_context_entry_creates_if_missing(db_path):
    from tether_mcp.server import _append_context_entry
    from db.queries import get_context_entries
    _append_context_entry("Brand New", "First content.")
    entries = get_context_entries(db_path)
    assert any(e["subject"] == "Brand New" for e in entries)


def test_patch_context_entry(db_path):
    from tether_mcp.server import _patch_context_entry
    from db.queries import get_context_entries
    _patch_context_entry("Job Applications", "ML engineer roles.", "ML + AI roles.")
    entries = get_context_entries(db_path)
    body = next(e["body"] for e in entries if e["subject"] == "Job Applications")
    assert "ML + AI roles." in body
    assert "ML engineer roles." not in body


def test_patch_context_entry_remove(db_path):
    from tether_mcp.server import _patch_context_entry
    from db.queries import get_context_entries
    _patch_context_entry("Job Applications", "ML engineer roles.", "")
    entries = get_context_entries(db_path)
    body = next(e["body"] for e in entries if e["subject"] == "Job Applications")
    assert "ML engineer roles." not in body


def test_patch_context_entry_not_found_raises():
    from tether_mcp.server import _patch_context_entry
    with pytest.raises(ValueError, match="No context entry found"):
        _patch_context_entry("Nonexistent", "x", "y")


def test_patch_context_entry_text_not_found_raises(db_path):
    from tether_mcp.server import _patch_context_entry
    with pytest.raises(ValueError, match="Text not found"):
        _patch_context_entry("Job Applications", "this text does not exist", "y")


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
