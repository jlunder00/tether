"""Tests for context_entries + milestones → context_nodes tree migration."""
import sqlite3
import pytest
from pathlib import Path
from db.schema import init_db
from db.migrate_context_tree import migrate_context_tree


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


def _insert_context(conn, subject, body, updated_at="2026-01-01 00:00:00"):
    conn.execute(
        "INSERT INTO context_entries (subject, body, updated_at) VALUES (?, ?, ?)",
        (subject, body, updated_at),
    )


def _insert_milestone(conn, id, context_subject, name, **kwargs):
    defaults = dict(
        description=None, target_date=None, status="pending",
        status_override=0, color=None,
    )
    defaults.update(kwargs)
    conn.execute(
        """INSERT INTO milestones
           (id, context_subject, name, description, target_date, status,
            status_override, color)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, context_subject, name, defaults["description"],
         defaults["target_date"], defaults["status"],
         defaults["status_override"], defaults["color"]),
    )


def _insert_task(conn, uuid, text, context_subject=None):
    conn.execute(
        "INSERT INTO tasks (uuid, text, context_subject) VALUES (?, ?, ?)",
        (uuid, text, context_subject),
    )


# ---------------------------------------------------------------------------
# Basic flat subject (no slashes)
# ---------------------------------------------------------------------------

def test_flat_subject_creates_single_node(db_path):
    conn = sqlite3.connect(db_path)
    _insert_context(conn, "Tether", "Main project notes")
    conn.commit()
    conn.close()

    migrate_context_tree(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    nodes = conn.execute("SELECT * FROM context_nodes").fetchall()
    assert len(nodes) == 1
    assert nodes[0]["name"] == "Tether"
    assert nodes[0]["parent_id"] is None
    assert nodes[0]["node_type"] == "context"

    sections = conn.execute("SELECT * FROM node_sections").fetchall()
    assert len(sections) == 1
    assert sections[0]["body"] == "Main project notes"
    assert sections[0]["section_type"] == "details"
    conn.close()


# ---------------------------------------------------------------------------
# Nested slash-separated subject
# ---------------------------------------------------------------------------

def test_nested_subject_creates_tree(db_path):
    conn = sqlite3.connect(db_path)
    _insert_context(conn, "School/ML/Project", "ML project details")
    conn.commit()
    conn.close()

    migrate_context_tree(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    nodes = conn.execute(
        "SELECT * FROM context_nodes ORDER BY name"
    ).fetchall()
    by_name = {n["name"]: n for n in nodes}

    assert len(nodes) == 3
    # Root node
    assert by_name["School"]["parent_id"] is None
    # Middle node
    assert by_name["ML"]["parent_id"] == by_name["School"]["id"]
    # Leaf node
    assert by_name["Project"]["parent_id"] == by_name["ML"]["id"]

    # Only the leaf (full subject) gets a body
    sections = conn.execute("SELECT * FROM node_sections").fetchall()
    assert len(sections) == 1
    assert sections[0]["node_id"] == by_name["Project"]["id"]
    conn.close()


# ---------------------------------------------------------------------------
# Shared prefix — both entries get their bodies
# ---------------------------------------------------------------------------

def test_shared_prefix_both_get_bodies(db_path):
    conn = sqlite3.connect(db_path)
    _insert_context(conn, "School", "School overview", updated_at="2026-02-01 00:00:00")
    _insert_context(conn, "School/ML", "ML class notes", updated_at="2026-03-01 00:00:00")
    conn.commit()
    conn.close()

    migrate_context_tree(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    nodes = conn.execute("SELECT * FROM context_nodes ORDER BY name").fetchall()
    by_name = {n["name"]: n for n in nodes}

    assert len(nodes) == 2
    assert by_name["School"]["parent_id"] is None
    assert by_name["ML"]["parent_id"] == by_name["School"]["id"]

    # Both should have node_sections entries
    sections = conn.execute(
        "SELECT ns.body, cn.name FROM node_sections ns "
        "JOIN context_nodes cn ON cn.id = ns.node_id ORDER BY cn.name"
    ).fetchall()
    assert len(sections) == 2
    sec_map = {s["name"]: s["body"] for s in sections}
    assert sec_map["ML"] == "ML class notes"
    assert sec_map["School"] == "School overview"

    # Verify updated_at is preserved
    assert by_name["School"]["updated_at"] == "2026-02-01 00:00:00"
    assert by_name["ML"]["updated_at"] == "2026-03-01 00:00:00"
    conn.close()


# ---------------------------------------------------------------------------
# Milestone migration
# ---------------------------------------------------------------------------

def test_milestone_becomes_child_node(db_path):
    conn = sqlite3.connect(db_path)
    _insert_context(conn, "Tether", "Project notes")
    _insert_milestone(
        conn, "ms-1", "Tether", "MVP Launch",
        description="Ship the first version",
        target_date="2026-06-01", status="in_progress",
        color="#ff0000",
    )
    conn.commit()
    conn.close()

    migrate_context_tree(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    nodes = conn.execute("SELECT * FROM context_nodes ORDER BY node_type").fetchall()
    by_type = {}
    for n in nodes:
        by_type.setdefault(n["node_type"], []).append(n)

    assert len(by_type["context"]) == 1
    assert len(by_type["milestone"]) == 1

    ms_node = by_type["milestone"][0]
    assert ms_node["id"] == "ms-1"
    assert ms_node["name"] == "MVP Launch"
    assert ms_node["parent_id"] == by_type["context"][0]["id"]
    assert ms_node["target_date"] == "2026-06-01"
    assert ms_node["status"] == "in_progress"
    assert ms_node["color"] == "#ff0000"

    # Milestone description → node_sections
    sections = conn.execute(
        "SELECT * FROM node_sections WHERE node_id = ?", (ms_node["id"],)
    ).fetchall()
    assert len(sections) == 1
    assert sections[0]["body"] == "Ship the first version"
    conn.close()


# ---------------------------------------------------------------------------
# milestone_tasks → node_tasks
# ---------------------------------------------------------------------------

def test_milestone_tasks_become_node_tasks(db_path):
    conn = sqlite3.connect(db_path)
    _insert_context(conn, "Proj", "notes")
    _insert_milestone(conn, "ms-2", "Proj", "Beta")
    _insert_task(conn, "t-1", "Build API")
    conn.execute(
        "INSERT INTO milestone_tasks (milestone_id, task_id) VALUES (?, ?)",
        ("ms-2", "t-1"),
    )
    conn.commit()
    conn.close()

    migrate_context_tree(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    nt = conn.execute("SELECT * FROM node_tasks").fetchall()
    assert len(nt) == 1
    assert nt[0]["node_id"] == "ms-2"
    assert nt[0]["task_id"] == "t-1"
    conn.close()


# ---------------------------------------------------------------------------
# tasks.context_subject → tasks.context_node_id
# ---------------------------------------------------------------------------

def test_task_context_node_id_set(db_path):
    conn = sqlite3.connect(db_path)
    _insert_context(conn, "Backend", "API work")
    _insert_task(conn, "t-10", "Fix auth bug", context_subject="Backend")
    _insert_task(conn, "t-11", "Misc task")
    conn.commit()
    conn.close()

    migrate_context_tree(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    t10 = conn.execute(
        "SELECT context_node_id FROM tasks WHERE uuid = ?", ("t-10",)
    ).fetchone()
    t11 = conn.execute(
        "SELECT context_node_id FROM tasks WHERE uuid = ?", ("t-11",)
    ).fetchone()

    assert t10["context_node_id"] is not None
    # Verify it points to the right node
    node = conn.execute(
        "SELECT name FROM context_nodes WHERE id = ?", (t10["context_node_id"],)
    ).fetchone()
    assert node["name"] == "Backend"

    assert t11["context_node_id"] is None
    conn.close()


# ---------------------------------------------------------------------------
# Idempotency — running twice is safe
# ---------------------------------------------------------------------------

def test_idempotent_second_run(db_path):
    conn = sqlite3.connect(db_path)
    _insert_context(conn, "X", "x body")
    conn.commit()
    conn.close()

    migrate_context_tree(db_path)
    migrate_context_tree(db_path)  # should not raise or duplicate

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM context_nodes").fetchone()[0]
    assert count == 1
    conn.close()


# ---------------------------------------------------------------------------
# Milestone with unknown context_subject is skipped
# ---------------------------------------------------------------------------

def test_orphan_milestone_skipped(db_path, capsys):
    conn = sqlite3.connect(db_path)
    _insert_context(conn, "Real", "exists")
    # Insert milestone referencing a subject not in context_entries
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """INSERT INTO milestones (id, context_subject, name, status, status_override)
           VALUES (?, ?, ?, 'pending', 0)""",
        ("ms-orphan", "DoesNotExist", "Ghost milestone"),
    )
    conn.commit()
    conn.close()

    migrate_context_tree(db_path)
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "DoesNotExist" in captured.out

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    nodes = conn.execute("SELECT * FROM context_nodes").fetchall()
    # Only the "Real" context node, no milestone node
    assert len(nodes) == 1
    assert nodes[0]["name"] == "Real"
    conn.close()


# ---------------------------------------------------------------------------
# Empty body is not inserted into node_sections
# ---------------------------------------------------------------------------

def test_empty_body_no_section(db_path):
    conn = sqlite3.connect(db_path)
    _insert_context(conn, "EmptyProject", "")
    conn.commit()
    conn.close()

    migrate_context_tree(db_path)

    conn = sqlite3.connect(db_path)
    sections = conn.execute("SELECT * FROM node_sections").fetchall()
    assert len(sections) == 0
    conn.close()
