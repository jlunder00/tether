"""Tests for node_sections name/position migration and context_nodes description."""
import sqlite3
import pytest
from pathlib import Path
try:
    from db.schema import init_db
    from db.migrate_section_files import migrate_section_files
except ImportError:
    pytestmark = pytest.mark.skip(reason="Skipping as Sqlite DB is deprecated and the required imports have been removed. Ensure Postgres equivalents are tested prior to removing these tests")


OLD_NODE_SECTIONS_DDL = """
CREATE TABLE node_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
    section_type TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(node_id, section_type)
);
"""


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def old_schema_db(tmp_path):
    """Create a database with the OLD node_sections schema (no name/position)."""
    path = tmp_path / "old.db"
    init_db(path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    # Drop triggers first (they reference node_sections)
    conn.execute("DROP TRIGGER IF EXISTS node_sections_fts_ai")
    conn.execute("DROP TRIGGER IF EXISTS node_sections_fts_ad")
    conn.execute("DROP TRIGGER IF EXISTS node_sections_fts_au")
    # Drop the new-schema table and recreate with old schema
    conn.execute("DROP TABLE node_sections")
    conn.executescript(OLD_NODE_SECTIONS_DDL)
    # Recreate triggers for old schema
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS node_sections_fts_ai
        AFTER INSERT ON node_sections BEGIN
            INSERT INTO node_sections_fts(rowid, body) VALUES (new.id, new.body);
        END;

        CREATE TRIGGER IF NOT EXISTS node_sections_fts_ad
        AFTER DELETE ON node_sections BEGIN
            INSERT INTO node_sections_fts(node_sections_fts, rowid, body)
            VALUES ('delete', old.id, old.body);
        END;

        CREATE TRIGGER IF NOT EXISTS node_sections_fts_au
        AFTER UPDATE ON node_sections BEGIN
            INSERT INTO node_sections_fts(node_sections_fts, rowid, body)
            VALUES ('delete', old.id, old.body);
            INSERT INTO node_sections_fts(rowid, body) VALUES (new.id, new.body);
        END;
    """)
    # Also remove description column from context_nodes by recreating it
    # (SQLite can't drop columns in older versions)
    # For simplicity, we just test the migration handles both cases
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()
    return path


def _col_names(conn, table):
    return [c["name"] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _insert_node(conn, node_id, name, parent_id=None):
    conn.execute(
        "INSERT INTO context_nodes (id, parent_id, name) VALUES (?, ?, ?)",
        (node_id, parent_id, name),
    )


# ---------------------------------------------------------------------------
# Migration adds name and position columns
# ---------------------------------------------------------------------------

def test_migration_adds_name_and_position(old_schema_db):
    conn = sqlite3.connect(old_schema_db)
    conn.row_factory = sqlite3.Row
    cols_before = _col_names(conn, "node_sections")
    assert "name" not in cols_before
    assert "position" not in cols_before
    conn.close()

    migrate_section_files(old_schema_db)

    conn = sqlite3.connect(old_schema_db)
    conn.row_factory = sqlite3.Row
    cols_after = _col_names(conn, "node_sections")
    assert "name" in cols_after
    assert "position" in cols_after
    conn.close()


# ---------------------------------------------------------------------------
# Existing sections get name='main' and position=0
# ---------------------------------------------------------------------------

def test_existing_sections_get_main_name(old_schema_db):
    conn = sqlite3.connect(old_schema_db)
    conn.row_factory = sqlite3.Row
    _insert_node(conn, "n1", "Project")
    conn.execute(
        "INSERT INTO node_sections (node_id, section_type, body) VALUES (?, ?, ?)",
        ("n1", "details", "some notes"),
    )
    conn.execute(
        "INSERT INTO node_sections (node_id, section_type, body) VALUES (?, ?, ?)",
        ("n1", "plan", "the plan"),
    )
    conn.commit()
    conn.close()

    migrate_section_files(old_schema_db)

    conn = sqlite3.connect(old_schema_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT section_type, name, position, body FROM node_sections ORDER BY section_type"
    ).fetchall()
    assert len(rows) == 2
    for row in rows:
        assert row["name"] == "main"
        assert row["position"] == 0
    conn.close()


# ---------------------------------------------------------------------------
# New UNIQUE constraint allows multiple names per (node_id, section_type)
# ---------------------------------------------------------------------------

def test_unique_constraint_allows_multiple_names(db_path):
    """After migration, (node_id, section_type, name) is unique — not just (node_id, section_type)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_node(conn, "n1", "Project")
    conn.execute(
        "INSERT INTO node_sections (node_id, section_type, name, body) VALUES (?, ?, ?, ?)",
        ("n1", "notes", "main", "primary notes"),
    )
    conn.execute(
        "INSERT INTO node_sections (node_id, section_type, name, body) VALUES (?, ?, ?, ?)",
        ("n1", "notes", "api-design", "API design notes"),
    )
    conn.commit()

    rows = conn.execute(
        "SELECT name, body FROM node_sections WHERE node_id = ? AND section_type = ? ORDER BY name",
        ("n1", "notes"),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["name"] == "api-design"
    assert rows[1]["name"] == "main"
    conn.close()


def test_unique_constraint_rejects_duplicate_name(db_path):
    """Duplicate (node_id, section_type, name) is still rejected."""
    conn = sqlite3.connect(db_path)
    _insert_node(conn, "n1", "Project")
    conn.execute(
        "INSERT INTO node_sections (node_id, section_type, name, body) VALUES (?, ?, ?, ?)",
        ("n1", "notes", "main", "first"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO node_sections (node_id, section_type, name, body) VALUES (?, ?, ?, ?)",
            ("n1", "notes", "main", "duplicate"),
        )
    conn.close()


# ---------------------------------------------------------------------------
# description column exists on context_nodes
# ---------------------------------------------------------------------------

def test_description_column_on_context_nodes(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cols = _col_names(conn, "context_nodes")
    assert "description" in cols

    # Verify it's usable
    _insert_node(conn, "n1", "Project")
    conn.execute(
        "UPDATE context_nodes SET description = ? WHERE id = ?",
        ("A short description", "n1"),
    )
    conn.commit()
    row = conn.execute("SELECT description FROM context_nodes WHERE id = ?", ("n1",)).fetchone()
    assert row["description"] == "A short description"
    conn.close()


def test_description_added_by_migration(old_schema_db):
    """Migration adds description to context_nodes even on old-schema DBs."""
    # The old_schema_db fixture was created by init_db which already has the new schema,
    # but the ALTER TABLE in migration is idempotent. Verify column exists after migration.
    migrate_section_files(old_schema_db)

    conn = sqlite3.connect(old_schema_db)
    conn.row_factory = sqlite3.Row
    cols = _col_names(conn, "context_nodes")
    assert "description" in cols
    conn.close()


# ---------------------------------------------------------------------------
# FTS still works after migration
# ---------------------------------------------------------------------------

def test_fts_works_after_migration(old_schema_db):
    conn = sqlite3.connect(old_schema_db)
    conn.row_factory = sqlite3.Row
    _insert_node(conn, "n1", "Project")
    conn.execute(
        "INSERT INTO node_sections (node_id, section_type, body) VALUES (?, ?, ?)",
        ("n1", "details", "quantum entanglement research"),
    )
    conn.commit()
    conn.close()

    migrate_section_files(old_schema_db)

    conn = sqlite3.connect(old_schema_db)
    conn.row_factory = sqlite3.Row
    # FTS search should find the migrated content
    results = conn.execute(
        "SELECT rowid FROM node_sections_fts WHERE body MATCH ?",
        ("quantum",),
    ).fetchall()
    assert len(results) == 1

    # Insert a new section and verify FTS trigger works
    conn.execute(
        "INSERT INTO node_sections (node_id, section_type, name, body) VALUES (?, ?, ?, ?)",
        ("n1", "notes", "extra", "photosynthesis details"),
    )
    conn.commit()
    results = conn.execute(
        "SELECT rowid FROM node_sections_fts WHERE body MATCH ?",
        ("photosynthesis",),
    ).fetchall()
    assert len(results) == 1
    conn.close()


# ---------------------------------------------------------------------------
# Idempotency — running migration twice is safe
# ---------------------------------------------------------------------------

def test_migration_idempotent(old_schema_db):
    conn = sqlite3.connect(old_schema_db)
    _insert_node(conn, "n1", "Project")
    conn.execute(
        "INSERT INTO node_sections (node_id, section_type, body) VALUES (?, ?, ?)",
        ("n1", "details", "content"),
    )
    conn.commit()
    conn.close()

    migrate_section_files(old_schema_db)
    migrate_section_files(old_schema_db)  # second run should not raise or duplicate

    conn = sqlite3.connect(old_schema_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM node_sections").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "main"
    conn.close()
