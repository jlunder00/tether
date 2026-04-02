#!/usr/bin/env python3
"""Migration: add dependencies, subtasks, links tables; add description to tasks; migrate task_dependencies."""
from pathlib import Path
import sqlite3


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)

    def try_exec(sql):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass

    # New tables
    conn.execute("""CREATE TABLE IF NOT EXISTS dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        blocker_type TEXT NOT NULL, blocker_id TEXT NOT NULL,
        blocked_type TEXT NOT NULL, blocked_id TEXT NOT NULL,
        UNIQUE (blocker_type, blocker_id, blocked_type, blocked_id))""")

    conn.execute("""CREATE TABLE IF NOT EXISTS subtasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL, text TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0)""")

    conn.execute("""CREATE TABLE IF NOT EXISTS links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_type TEXT NOT NULL, parent_id TEXT NOT NULL,
        url TEXT NOT NULL, label TEXT,
        category TEXT NOT NULL DEFAULT 'other',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")

    # Add description column to tasks
    try_exec("ALTER TABLE tasks ADD COLUMN description TEXT")

    # Migrate task_dependencies → dependencies
    try:
        rows = conn.execute("SELECT task_id, blocked_by_id FROM task_dependencies").fetchall()
        for task_id, blocked_by_id in rows:
            conn.execute(
                "INSERT OR IGNORE INTO dependencies (blocker_type, blocker_id, blocked_type, blocked_id) VALUES (?, ?, ?, ?)",
                ("task", blocked_by_id, "task", task_id),
            )
        print(f"Migrated {len(rows)} task_dependencies rows")
    except sqlite3.OperationalError:
        print("No task_dependencies table found — skipping migration")

    conn.commit()
    conn.close()
    print("Data model migration complete.")


if __name__ == "__main__":
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".tether-config" / "tether.db"
    migrate(path)
