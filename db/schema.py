from __future__ import annotations
import sqlite3
from pathlib import Path


DDL = """
CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    time TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    flexibility TEXT NOT NULL DEFAULT 'flexible',
    strictness INTEGER NOT NULL DEFAULT 3,
    color TEXT NOT NULL DEFAULT '#888888',
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS plans (
    date TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_date TEXT NOT NULL REFERENCES plans(date) ON DELETE CASCADE,
    anchor_id TEXT NOT NULL REFERENCES anchors(id),
    position INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS acknowledgements (
    plan_date TEXT NOT NULL,
    anchor_id TEXT NOT NULL,
    acknowledged_at TEXT NOT NULL,
    PRIMARY KEY (plan_date, anchor_id)
);

CREATE TABLE IF NOT EXISTS check_ins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_date TEXT NOT NULL,
    anchor_id TEXT NOT NULL,
    type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    accomplished TEXT NOT NULL DEFAULT '',
    current_status TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS context_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT UNIQUE NOT NULL,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    record_id TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_history (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    body TEXT NOT NULL,
    ts   DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    with get_db(db_path) as conn:
        conn.executescript(DDL)
