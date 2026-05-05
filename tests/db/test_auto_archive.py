"""Tests for auto-archive query and user settings functions."""
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    from db.schema import init_db, get_db
    from db import queries as q
except ImportError:
    pytestmark = pytest.mark.skip(reason="Skipping as Sqlite DB is deprecated and the required imports have been removed. Ensure Postgres equivalents are tested prior to removing these tests")


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


def _insert_task(db_path, uuid, text, status="pending"):
    """Helper: insert a bare task directly."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO tasks (uuid, text, status) VALUES (?, ?, ?)",
            (uuid, text, status),
        )


def _set_node_updated_at(db_path, node_id, days_ago):
    """Helper: set a node's updated_at to N days in the past."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE context_nodes SET updated_at = ? WHERE id = ?",
            (ts, node_id),
        )


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

class TestUserSettings:
    def test_get_missing_setting_returns_none(self, db_path):
        assert q.get_user_setting(db_path, "u1", "nonexistent") is None

    def test_set_and_get_setting(self, db_path):
        q.set_user_setting(db_path, "u1", "theme", "dark")
        assert q.get_user_setting(db_path, "u1", "theme") == "dark"

    def test_upsert_overwrites(self, db_path):
        q.set_user_setting(db_path, "u1", "theme", "dark")
        q.set_user_setting(db_path, "u1", "theme", "light")
        assert q.get_user_setting(db_path, "u1", "theme") == "light"

    def test_get_all_settings(self, db_path):
        q.set_user_setting(db_path, "u1", "a", "1")
        q.set_user_setting(db_path, "u1", "b", "2")
        result = q.get_all_user_settings(db_path, "u1")
        assert result == {"a": "1", "b": "2"}

    def test_settings_isolated_per_user(self, db_path):
        q.set_user_setting(db_path, "u1", "k", "v1")
        q.set_user_setting(db_path, "u2", "k", "v2")
        assert q.get_user_setting(db_path, "u1", "k") == "v1"
        assert q.get_user_setting(db_path, "u2", "k") == "v2"


# ---------------------------------------------------------------------------
# get_auto_archivable_nodes
# ---------------------------------------------------------------------------

class TestAutoArchivableNodes:
    def test_no_criteria_returns_empty(self, db_path):
        q.create_node(db_path, None, "Project")
        assert q.get_auto_archivable_nodes(db_path) == []

    def test_inactive_node_found(self, db_path):
        node = q.create_node(db_path, None, "Old Project")
        _set_node_updated_at(db_path, node["id"], days_ago=15)

        result = q.get_auto_archivable_nodes(db_path, days_inactive=10)
        assert len(result) == 1
        assert result[0]["id"] == node["id"]

    def test_recently_updated_node_not_found(self, db_path):
        node = q.create_node(db_path, None, "Active")
        _set_node_updated_at(db_path, node["id"], days_ago=3)

        result = q.get_auto_archivable_nodes(db_path, days_inactive=10)
        assert len(result) == 0

    def test_already_archived_excluded(self, db_path):
        node = q.create_node(db_path, None, "Archived Already")
        _set_node_updated_at(db_path, node["id"], days_ago=60)
        q.archive_node(db_path, node["id"])
        # Reset updated_at after archiving (archive_node updates it)
        _set_node_updated_at(db_path, node["id"], days_ago=60)

        result = q.get_auto_archivable_nodes(db_path, days_inactive=10)
        assert len(result) == 0

    def test_completed_tasks_node_found(self, db_path):
        node = q.create_node(db_path, None, "Done Project")
        _insert_task(db_path, "t1", "Task 1", status="done")
        _insert_task(db_path, "t2", "Task 2", status="done")
        q.link_task_to_node(db_path, node["id"], "t1")
        q.link_task_to_node(db_path, node["id"], "t2")
        _set_node_updated_at(db_path, node["id"], days_ago=10)

        result = q.get_auto_archivable_nodes(db_path, days_completed=7)
        assert len(result) == 1
        assert result[0]["id"] == node["id"]

    def test_partially_done_tasks_not_found(self, db_path):
        node = q.create_node(db_path, None, "Partial")
        _insert_task(db_path, "t1", "Done", status="done")
        _insert_task(db_path, "t2", "Pending", status="pending")
        q.link_task_to_node(db_path, node["id"], "t1")
        q.link_task_to_node(db_path, node["id"], "t2")
        _set_node_updated_at(db_path, node["id"], days_ago=10)

        result = q.get_auto_archivable_nodes(db_path, days_completed=7)
        assert len(result) == 0

    def test_completed_but_recent_not_found(self, db_path):
        node = q.create_node(db_path, None, "Recently Done")
        _insert_task(db_path, "t1", "Task", status="done")
        q.link_task_to_node(db_path, node["id"], "t1")
        _set_node_updated_at(db_path, node["id"], days_ago=2)

        result = q.get_auto_archivable_nodes(db_path, days_completed=7)
        assert len(result) == 0

    def test_no_tasks_excluded_from_completed_check(self, db_path):
        """A node with no linked tasks should NOT match days_completed."""
        node = q.create_node(db_path, None, "No Tasks")
        _set_node_updated_at(db_path, node["id"], days_ago=30)

        result = q.get_auto_archivable_nodes(db_path, days_completed=7)
        assert len(result) == 0

    def test_both_criteria_union(self, db_path):
        """When both criteria are given, nodes matching either are returned."""
        # Node 1: inactive only (no tasks)
        n1 = q.create_node(db_path, None, "Inactive")
        _set_node_updated_at(db_path, n1["id"], days_ago=20)

        # Node 2: completed tasks only (also old enough for inactive, but test union)
        n2 = q.create_node(db_path, None, "Completed")
        _insert_task(db_path, "t1", "Task", status="done")
        q.link_task_to_node(db_path, n2["id"], "t1")
        _set_node_updated_at(db_path, n2["id"], days_ago=10)

        # Node 3: active, not done — should NOT appear
        n3 = q.create_node(db_path, None, "Active")
        _set_node_updated_at(db_path, n3["id"], days_ago=1)

        result = q.get_auto_archivable_nodes(db_path, days_completed=7, days_inactive=15)
        ids = {n["id"] for n in result}
        assert n1["id"] in ids
        assert n2["id"] in ids
        assert n3["id"] not in ids
