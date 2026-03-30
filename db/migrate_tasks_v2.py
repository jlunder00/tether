#!/usr/bin/env python3
"""One-time migration: add uuid/status/followup_config to tasks; followup_config to anchors."""
import sqlite3
import uuid
from pathlib import Path

DB_PATH = Path.home() / ".tether-config" / "tether.db"


def migrate(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")

    def try_alter(sql: str) -> None:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists

    try_alter("ALTER TABLE tasks ADD COLUMN uuid TEXT")
    try_alter("ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
    try_alter("ALTER TABLE tasks ADD COLUMN followup_config TEXT")
    try_alter("ALTER TABLE anchors ADD COLUMN followup_config TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_dependencies (
            task_id       TEXT NOT NULL,
            blocked_by_id TEXT NOT NULL,
            PRIMARY KEY (task_id, blocked_by_id)
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_uuid ON tasks(uuid)"
    )

    rows = conn.execute("SELECT id FROM tasks WHERE uuid IS NULL").fetchall()
    for (row_id,) in rows:
        conn.execute("UPDATE tasks SET uuid=? WHERE id=?", (str(uuid.uuid4()), row_id))

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    print(f"Migration complete — backfilled UUIDs for {len(rows)} existing tasks.")


if __name__ == "__main__":
    migrate()
