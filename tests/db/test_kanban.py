import pytest
from pathlib import Path
try:
    from db.schema import init_db
    from db.queries import (
        seed_kanban_columns, get_kanban_columns,
        create_kanban_column, update_kanban_column, delete_kanban_column,
    )
except ImportError:
    pytestmark = pytest.mark.skip(reason="Skipping as Sqlite DB is deprecated and the required imports have been removed. Ensure Postgres equivalents are tested prior to removing these tests")

@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path

def test_seed_creates_default_columns(db_path):
    seed_kanban_columns(db_path)
    cols = get_kanban_columns(db_path)
    assert len(cols) == 6
    names = [c["name"] for c in cols]
    assert "Backlog" in names
    assert "Pending" in names
    assert "In Progress" in names
    assert "Done" in names
    assert "Skipped" in names
    assert "Blocked" in names

def test_seed_is_idempotent(db_path):
    seed_kanban_columns(db_path)
    seed_kanban_columns(db_path)
    assert len(get_kanban_columns(db_path)) == 6

def test_get_kanban_columns_filters_by_user(db_path):
    seed_kanban_columns(db_path)
    create_kanban_column(db_path, "Custom", 10, "#ff0000", {"status": "review"}, {"set_status": "review"}, "user1")
    # All visible to user1: 6 built-in + 1 user-defined
    cols = get_kanban_columns(db_path, user_id="user1")
    assert len(cols) == 7
    # User2 sees only built-in
    cols2 = get_kanban_columns(db_path, user_id="user2")
    assert len(cols2) == 6

def test_create_kanban_column(db_path):
    col = create_kanban_column(db_path, "Blocked", 5, "#ef4444",
                                {"status": "blocked"}, {"set_status": "blocked"}, "user1")
    assert col["id"]
    assert col["name"] == "Blocked"
    assert col["created_by"] == "user1"

def test_update_kanban_column(db_path):
    seed_kanban_columns(db_path)
    cols = get_kanban_columns(db_path)
    col_id = cols[0]["id"]
    updated = update_kanban_column(db_path, col_id, {"name": "Renamed", "color": "#000"})
    assert updated["name"] == "Renamed"
    assert updated["color"] == "#000"

def test_delete_kanban_column(db_path):
    col = create_kanban_column(db_path, "Temp", 99, None, {}, {}, "user1")
    delete_kanban_column(db_path, col["id"])
    cols = get_kanban_columns(db_path, user_id="user1")
    assert not any(c["id"] == col["id"] for c in cols)
