#!/usr/bin/env python3
"""One-time migration: add followup_state table (followup_config columns already exist in schema)."""
from pathlib import Path
import sqlite3

DB_PATH = Path.home() / ".tether-config" / "tether.db"


def migrate(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")

    def try_alter(sql: str) -> None:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists

    # These are no-ops on current Pi DB since columns already exist,
    # but safe to run for any older installations.
    try_alter("ALTER TABLE anchors ADD COLUMN followup_config TEXT")
    try_alter("ALTER TABLE tasks ADD COLUMN followup_config TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS followup_state (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            date                 TEXT NOT NULL,
            anchor_id            TEXT NOT NULL,
            task_id              TEXT NOT NULL,
            sequence_started_at  DATETIME NOT NULL,
            acknowledged_at      DATETIME,
            pre_ack_pings_sent   INTEGER DEFAULT 0,
            post_ack_pings_sent  INTEGER DEFAULT 0,
            last_ping_at         DATETIME,
            completed            INTEGER DEFAULT 0,
            UNIQUE (date, task_id)
        )
    """)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    print("Migration complete — followup_state table created.")


if __name__ == "__main__":
    migrate()
