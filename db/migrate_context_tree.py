#!/usr/bin/env python3
"""One-time migration: flat context_entries + milestones → context_nodes tree."""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path


def migrate_context_tree(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")

    # 1. Check if already migrated
    count = conn.execute("SELECT COUNT(*) FROM context_nodes").fetchone()[0]
    if count > 0:
        print("  context_nodes already populated — skipping migration")
        conn.close()
        return

    # 2. Add context_node_id column to tasks (idempotent)
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN context_node_id TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

    # --- Begin single transaction ---
    conn.execute("BEGIN")

    # Cache: slash-separated path → node_id
    path_to_node: dict[str, str] = {}

    def ensure_path(path: str, updated_at: str | None = None) -> str:
        """Walk the slash-separated path, creating intermediate nodes as needed.
        Returns the node_id for the final segment."""
        if path in path_to_node:
            return path_to_node[path]

        parts = path.split("/")
        current_path = ""
        parent_id = None

        for segment in parts:
            current_path = f"{current_path}/{segment}" if current_path else segment
            if current_path in path_to_node:
                parent_id = path_to_node[current_path]
                continue

            node_id = str(uuid.uuid4())
            ts = updated_at if current_path == path else None
            conn.execute(
                """INSERT INTO context_nodes (id, parent_id, name, node_type, updated_at)
                   VALUES (?, ?, ?, 'context', COALESCE(?, CURRENT_TIMESTAMP))""",
                (node_id, parent_id, segment, ts),
            )
            path_to_node[current_path] = node_id
            parent_id = node_id

        return path_to_node[path]

    # 3. Migrate context_entries → context_nodes + node_sections
    rows = conn.execute("SELECT subject, body, updated_at FROM context_entries").fetchall()
    for row in rows:
        subject, body, updated_at = row["subject"], row["body"], row["updated_at"]
        node_id = ensure_path(subject, updated_at=updated_at)

        # Update updated_at on the leaf node (ensure_path may have been called
        # earlier as an intermediate, so force the correct timestamp)
        conn.execute(
            "UPDATE context_nodes SET updated_at = ? WHERE id = ?",
            (updated_at, node_id),
        )

        # Insert body into node_sections
        if body:
            conn.execute(
                """INSERT OR REPLACE INTO node_sections (node_id, section_type, body, updated_at)
                   VALUES (?, 'details', ?, ?)""",
                (node_id, body, updated_at),
            )

    # 4. Migrate milestones → context_nodes (node_type='milestone')
    milestones = conn.execute(
        "SELECT id, context_subject, name, description, target_date, "
        "status, status_override, color, created_at, updated_at FROM milestones"
    ).fetchall()
    for ms in milestones:
        parent_node_id = path_to_node.get(ms["context_subject"])
        if parent_node_id is None:
            print(f"  WARNING: milestone '{ms['name']}' references unknown context_subject "
                  f"'{ms['context_subject']}' — skipping")
            continue

        conn.execute(
            """INSERT INTO context_nodes
               (id, parent_id, name, node_type, target_date, status,
                status_override, color, created_at, updated_at)
               VALUES (?, ?, ?, 'milestone', ?, ?, ?, ?, ?, ?)""",
            (
                ms["id"],
                parent_node_id,
                ms["name"],
                ms["target_date"],
                ms["status"],
                ms["status_override"],
                ms["color"],
                ms["created_at"],
                ms["updated_at"],
            ),
        )

        if ms["description"]:
            conn.execute(
                """INSERT INTO node_sections (node_id, section_type, body, updated_at)
                   VALUES (?, 'details', ?, ?)""",
                (ms["id"], ms["description"], ms["updated_at"]),
            )

    # 5. Migrate milestone_tasks → node_tasks
    mt_rows = conn.execute("SELECT milestone_id, task_id FROM milestone_tasks").fetchall()
    for mt in mt_rows:
        # Only migrate if the milestone was actually migrated (not skipped)
        exists = conn.execute(
            "SELECT 1 FROM context_nodes WHERE id = ?", (mt["milestone_id"],)
        ).fetchone()
        if exists:
            conn.execute(
                "INSERT INTO node_tasks (node_id, task_id) VALUES (?, ?)",
                (mt["milestone_id"], mt["task_id"]),
            )

    # 6. Migrate tasks.context_subject → tasks.context_node_id
    tasks_with_ctx = conn.execute(
        "SELECT uuid, context_subject FROM tasks WHERE context_subject IS NOT NULL"
    ).fetchall()
    for task in tasks_with_ctx:
        node_id = path_to_node.get(task["context_subject"])
        if node_id:
            conn.execute(
                "UPDATE tasks SET context_node_id = ? WHERE uuid = ?",
                (node_id, task["uuid"]),
            )

    # 7. Rebuild FTS index
    try:
        conn.execute("INSERT INTO node_sections_fts(node_sections_fts) VALUES('rebuild')")
    except sqlite3.OperationalError:
        pass  # FTS table may not exist in older schemas

    conn.execute("COMMIT")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        print(f"Migrating {path}...")
        migrate_context_tree(Path(path))
        print("  done")
