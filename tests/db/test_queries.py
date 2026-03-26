import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import (
    upsert_anchor, get_anchors,
    upsert_plan, get_plan,
    upsert_tasks,
    upsert_context_entry, get_context_entries, delete_context_entry,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


def test_init_creates_tables(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"anchors", "plans", "tasks", "acknowledgements", "context_entries", "edit_history"} <= tables


def test_upsert_and_get_anchor(db_path):
    upsert_anchor(db_path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                             "duration_minutes": 120, "flexibility": "locked",
                             "strictness": 4, "color": "#e05c5c", "position": 1})
    anchors = get_anchors(db_path)
    assert any(a["id"] == "grind_am" for a in anchors)
    assert anchors[0]["name"] == "The Grind"


def test_upsert_and_get_plan(db_path):
    upsert_plan(db_path, "2026-03-26")
    plan = get_plan(db_path, "2026-03-26")
    assert plan["date"] == "2026-03-26"
    assert plan["anchors"] == {}


def test_upsert_tasks_replaces_anchor_tasks(db_path):
    upsert_anchor(db_path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                             "duration_minutes": 120, "flexibility": "locked",
                             "strictness": 4, "color": "#e05c5c", "position": 1})
    upsert_plan(db_path, "2026-03-26")
    upsert_tasks(db_path, "2026-03-26", "grind_am",
                 tasks=["Apply to 3 jobs", "Follow up Stripe"], notes="ML roles")
    plan = get_plan(db_path, "2026-03-26")
    assert plan["anchors"]["grind_am"]["tasks"] == ["Apply to 3 jobs", "Follow up Stripe"]
    assert plan["anchors"]["grind_am"]["notes"] == "ML roles"


def test_upsert_tasks_replaces_existing(db_path):
    upsert_anchor(db_path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                             "duration_minutes": 120, "flexibility": "locked",
                             "strictness": 4, "color": "#e05c5c", "position": 1})
    upsert_plan(db_path, "2026-03-26")
    upsert_tasks(db_path, "2026-03-26", "grind_am", tasks=["Old task"], notes="")
    upsert_tasks(db_path, "2026-03-26", "grind_am", tasks=["New task"], notes="")
    plan = get_plan(db_path, "2026-03-26")
    assert plan["anchors"]["grind_am"]["tasks"] == ["New task"]


def test_context_entry_crud(db_path):
    upsert_context_entry(db_path, "Job Applications",
                         "Applying for ML engineer roles. Priority 1.")
    entries = get_context_entries(db_path)
    assert any(e["subject"] == "Job Applications" for e in entries)

    upsert_context_entry(db_path, "Job Applications", "Updated body.")
    entries = get_context_entries(db_path)
    match = next(e for e in entries if e["subject"] == "Job Applications")
    assert match["body"] == "Updated body."

    delete_context_entry(db_path, "Job Applications")
    entries = get_context_entries(db_path)
    assert not any(e["subject"] == "Job Applications" for e in entries)
