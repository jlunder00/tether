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
    position INTEGER NOT NULL DEFAULT 0,
    followup_config TEXT
);

CREATE TABLE IF NOT EXISTS plans (
    date TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE,
    plan_date TEXT,
    anchor_id TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    followup_config TEXT,
    notes TEXT NOT NULL DEFAULT '',
    description TEXT,
    context_subject TEXT
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id       TEXT NOT NULL,
    blocked_by_id TEXT NOT NULL,
    PRIMARY KEY (task_id, blocked_by_id)
);

CREATE TABLE IF NOT EXISTS dependencies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    blocker_type TEXT NOT NULL,
    blocker_id   TEXT NOT NULL,
    blocked_type TEXT NOT NULL,
    blocked_id   TEXT NOT NULL,
    UNIQUE (blocker_type, blocker_id, blocked_type, blocked_id)
);

CREATE TABLE IF NOT EXISTS subtasks (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id  TEXT NOT NULL,
    text     TEXT NOT NULL,
    done     INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_type TEXT NOT NULL,
    parent_id   TEXT NOT NULL,
    url         TEXT NOT NULL,
    label       TEXT,
    category    TEXT NOT NULL DEFAULT 'other',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_context (
    task_id  TEXT NOT NULL,
    subject  TEXT NOT NULL REFERENCES context_entries(subject) ON DELETE CASCADE,
    PRIMARY KEY (task_id, subject)
);

CREATE TABLE IF NOT EXISTS milestones (
    id              TEXT PRIMARY KEY,
    context_subject TEXT NOT NULL REFERENCES context_entries(subject) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    target_date     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    status_override INTEGER NOT NULL DEFAULT 0,
    color           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS milestone_tasks (
    milestone_id TEXT NOT NULL REFERENCES milestones(id) ON DELETE CASCADE,
    task_id      TEXT NOT NULL,
    PRIMARY KEY (milestone_id, task_id)
);

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

CREATE TABLE IF NOT EXISTS staging_mutations (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    type        TEXT NOT NULL,
    description TEXT NOT NULL,
    params_json TEXT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orchestrator_conversation (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    body        TEXT NOT NULL,
    round_num   INTEGER NOT NULL,
    ts          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invocation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    stage       TEXT NOT NULL,
    prompt      TEXT NOT NULL DEFAULT '',
    response    TEXT NOT NULL DEFAULT '',
    error       TEXT,
    ts          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS state_monitor_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    change_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL DEFAULT '',
    score       INTEGER NOT NULL DEFAULT 1,
    consumed    INTEGER NOT NULL DEFAULT 0,
    ts          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS beacon_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    last_invoked_at  DATETIME
);

INSERT OR IGNORE INTO beacon_state (id, last_invoked_at) VALUES (1, NULL);

CREATE TABLE IF NOT EXISTS kanban_columns (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    color       TEXT,
    match_rules TEXT NOT NULL DEFAULT '{}',
    entry_rules TEXT NOT NULL DEFAULT '{}',
    created_by  TEXT
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS context_nodes (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES context_nodes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'context',
    archived INTEGER NOT NULL DEFAULT 0,
    target_date TEXT,
    status TEXT DEFAULT 'pending',
    status_override INTEGER NOT NULL DEFAULT 0,
    color TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_id, name)
);

CREATE TABLE IF NOT EXISTS node_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
    section_type TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(node_id, section_type)
);

CREATE TABLE IF NOT EXISTS node_tasks (
    node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    PRIMARY KEY (node_id, task_id)
);
"""

_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    chat_id     TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'active',
    turn_count  INTEGER NOT NULL DEFAULT 0,
    max_turns   INTEGER NOT NULL DEFAULT 10,
    summary     TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_activity DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sessions_chat_active
ON sessions(chat_id, state)
WHERE state IN ('active', 'waiting_user');
"""


def get_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    with get_db(db_path) as conn:
        conn.executescript(DDL)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS node_sections_fts USING fts5(
                body,
                content='node_sections',
                content_rowid='id'
            )
        """)
        conn.executescript(_SESSIONS_DDL)
