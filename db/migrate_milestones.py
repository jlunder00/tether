#!/usr/bin/env python3
"""One-time migration: add milestones and milestone_tasks tables."""
from pathlib import Path
import sqlite3

DB_PATH = Path.home() / ".tether-config" / "tether.db"


def migrate(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS milestones (
            id              TEXT PRIMARY KEY,
            context_subject TEXT NOT NULL REFERENCES context_entries(subject) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            description     TEXT,
            target_date     TEXT,
            status          TEXT NOT NULL DEFAULT 'pending',
            status_override INTEGER NOT NULL DEFAULT 0,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS milestone_tasks (
            milestone_id TEXT NOT NULL REFERENCES milestones(id) ON DELETE CASCADE,
            task_id      TEXT NOT NULL,
            PRIMARY KEY (milestone_id, task_id)
        )
    """)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    print("Migration complete — milestones and milestone_tasks tables created.")


if __name__ == "__main__":
    migrate()
