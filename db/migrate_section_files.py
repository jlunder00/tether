#!/usr/bin/env python3
"""Migration: add name/position columns to node_sections, description to context_nodes."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


def migrate_section_files(db_path: Path) -> None:
    # Ensure all tables exist (new schema)
    from db.schema import init_db
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        # 1. Add description column to context_nodes (idempotent)
        try:
            conn.execute("ALTER TABLE context_nodes ADD COLUMN description TEXT")
            print("  Added description column to context_nodes")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
            print("  description column already exists on context_nodes")

        # 2. Check if node_sections already has the name column
        if _column_exists(conn, "node_sections", "name"):
            print("  node_sections already has name column — skipping table recreation")
            return

        # 3. Recreate node_sections with new schema
        conn.execute("BEGIN")

        conn.execute("""
            CREATE TABLE node_sections_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
                section_type TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT 'main',
                body TEXT NOT NULL DEFAULT '',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                position INTEGER NOT NULL DEFAULT 0,
                UNIQUE(node_id, section_type, name)
            )
        """)

        conn.execute("""
            INSERT INTO node_sections_new (id, node_id, section_type, name, body, updated_at, position)
            SELECT id, node_id, section_type, 'main', body, updated_at, 0
            FROM node_sections
        """)

        # DROP TABLE silently removes triggers attached to it
        conn.execute("DROP TABLE node_sections")
        conn.execute("ALTER TABLE node_sections_new RENAME TO node_sections")

        # Recreate FTS5 sync triggers (lost when old table was dropped)
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

        # 4. Rebuild FTS5 index
        try:
            conn.execute("INSERT INTO node_sections_fts(node_sections_fts) VALUES('rebuild')")
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                print("  INFO: node_sections_fts table does not exist — skipping FTS rebuild")
            else:
                raise

        conn.execute("COMMIT")
        print("  Migrated node_sections: added name, position columns")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        print(f"Migrating {path}...")
        migrate_section_files(Path(path))
        print("  done")
