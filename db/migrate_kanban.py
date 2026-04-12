#!/usr/bin/env python3
"""Migration: add context_subject to tasks, create kanban_columns + user_settings tables."""
from pathlib import Path
import sqlite3
import sys

DB_PATH = Path.home() / ".tether-config" / "tether.db"


def migrate(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)

    def try_alter(sql):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                pass
            else:
                raise

    # Add context_subject to tasks
    try_alter("ALTER TABLE tasks ADD COLUMN context_subject TEXT")

    # Populate from task_context (first link per task)
    try:
        conn.execute("""
            UPDATE tasks SET context_subject = (
                SELECT subject FROM task_context WHERE task_id = tasks.uuid LIMIT 1
            ) WHERE context_subject IS NULL
        """)
    except sqlite3.OperationalError:
        pass  # task_context may not exist

    # Create kanban_columns table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kanban_columns (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            position    INTEGER NOT NULL DEFAULT 0,
            color       TEXT,
            match_rules TEXT NOT NULL DEFAULT '{}',
            entry_rules TEXT NOT NULL DEFAULT '{}',
            created_by  TEXT
        )
    """)

    # Create user_settings table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT NOT NULL,
            key     TEXT NOT NULL,
            value   TEXT NOT NULL,
            PRIMARY KEY (user_id, key)
        )
    """)

    conn.commit()
    conn.close()

    # Seed default kanban columns
    from db.queries import seed_kanban_columns
    seed_kanban_columns(db_path)

    print(f"Migration complete — {db_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for path in sys.argv[1:]:
            migrate(Path(path))
    else:
        migrate()
