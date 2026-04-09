#!/usr/bin/env python3
"""Migration: add color to milestones, make plan_date/anchor_id nullable on tasks."""
from pathlib import Path
import sqlite3

DB_PATH = Path.home() / ".tether-config" / "tether.db"


def migrate(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)

    def try_alter(sql: str) -> None:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass

    try_alter("ALTER TABLE milestones ADD COLUMN color TEXT")
    # SQLite doesn't support ALTER COLUMN, so recreate tasks table with nullable columns
    try:
        conn.execute("INSERT INTO tasks (uuid, plan_date, anchor_id, text) VALUES ('__test_null__', NULL, NULL, 'test')")
        conn.execute("DELETE FROM tasks WHERE uuid='__test_null__'")
    except sqlite3.IntegrityError:
        # Check which columns the existing table has
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        has_description = "description" in cols
        if has_description:
            select_sql = "SELECT id, uuid, plan_date, anchor_id, position, text, status, followup_config, notes, description FROM tasks"
        else:
            select_sql = "SELECT id, uuid, plan_date, anchor_id, position, text, status, followup_config, notes, NULL FROM tasks"
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DROP TABLE IF EXISTS tasks_new")
        conn.execute("""
            CREATE TABLE tasks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE,
                plan_date TEXT,
                anchor_id TEXT,
                position INTEGER NOT NULL DEFAULT 0,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                followup_config TEXT,
                notes TEXT NOT NULL DEFAULT '',
                description TEXT
            )
        """)
        conn.execute(f"INSERT INTO tasks_new {select_sql}")
        conn.execute("DROP TABLE tasks")
        conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
        conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()
    print("Migration complete — milestone color + nullable task plan_date/anchor_id.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        for path in sys.argv[1:]:
            print(f"Migrating {path}...")
            migrate(Path(path))
    else:
        migrate()
