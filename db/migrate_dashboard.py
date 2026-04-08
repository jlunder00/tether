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
        conn.executescript("""
            PRAGMA foreign_keys = OFF;
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
            );
            INSERT INTO tasks_new SELECT * FROM tasks;
            DROP TABLE tasks;
            ALTER TABLE tasks_new RENAME TO tasks;
            PRAGMA foreign_keys = ON;
        """)
    conn.commit()
    conn.close()
    print("Migration complete — milestone color + nullable task plan_date/anchor_id.")


if __name__ == "__main__":
    migrate()
