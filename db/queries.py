from __future__ import annotations
import json
import logging
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from db.schema import get_db

logger = logging.getLogger(__name__)


def _row_to_task(row, *, include_schedule: bool = False) -> dict:
    """Convert a DB row to a task dict. Shared by all task-returning functions."""
    r = dict(row)  # sqlite3.Row -> dict so .get() works
    fc = r.get("followup_config")
    d = {
        "id": r["uuid"],
        "text": r["text"],
        "status": r["status"] or "pending",
        "position": r.get("position", 0),
        "description": r.get("description"),
        "context_subject": r.get("context_subject"),
        "followup_config": json.loads(fc) if fc else None,
        "blocks": [],
        "blocked_by": [],
    }
    if include_schedule:
        d["plan_date"] = r.get("plan_date")
        d["anchor_id"] = r.get("anchor_id")
    return d


def upsert_anchor(db_path: Path, anchor: dict) -> None:
    fc_json = json.dumps(anchor.get("followup_config")) if anchor.get("followup_config") is not None else None
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO anchors (id, name, time, duration_minutes, flexibility, strictness, color, position, followup_config)
            VALUES (:id, :name, :time, :duration_minutes, :flexibility, :strictness, :color, :position, :followup_config)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, time=excluded.time,
                duration_minutes=excluded.duration_minutes,
                flexibility=excluded.flexibility, strictness=excluded.strictness,
                color=excluded.color, position=excluded.position,
                followup_config=excluded.followup_config
        """, {**anchor, "followup_config": fc_json})


def delete_anchor(db_path: Path, anchor_id: str) -> None:
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM anchors WHERE id=?", (anchor_id,))


def seed_default_anchors(db_path: Path) -> None:
    """Create a simple default schedule for new users. Skips if anchors already exist."""
    with get_db(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM anchors").fetchone()[0]
        if count > 0:
            return
    defaults = [
        {"id": "morning", "name": "Morning", "time": "08:00", "duration_minutes": 120,
         "flexibility": "flexible", "strictness": 3, "color": "#5b8dee", "position": 0},
        {"id": "midday", "name": "Midday", "time": "10:00", "duration_minutes": 150,
         "flexibility": "flexible", "strictness": 3, "color": "#7c6af7", "position": 1},
        {"id": "afternoon", "name": "Afternoon", "time": "13:00", "duration_minutes": 180,
         "flexibility": "flexible", "strictness": 3, "color": "#e05c5c", "position": 2},
        {"id": "evening", "name": "Evening", "time": "17:00", "duration_minutes": 120,
         "flexibility": "flexible", "strictness": 2, "color": "#4caf8c", "position": 3},
    ]
    for anchor in defaults:
        upsert_anchor(db_path, anchor)


def get_anchors(db_path: Path) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM anchors ORDER BY position").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            fc = d.get("followup_config")
            d["followup_config"] = json.loads(fc) if fc else None
            result.append(d)
        return result


def upsert_plan(db_path: Path, date: str) -> None:
    with get_db(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO plans (date) VALUES (?)", (date,))


def get_plan(db_path: Path, date: str) -> dict:
    with get_db(db_path) as conn:
        plan_row = conn.execute("SELECT date FROM plans WHERE date=?", (date,)).fetchone()
        if not plan_row:
            return {"date": date, "anchors": {}, "acknowledgements": {}, "check_in_log": []}

        # Detect available columns so we work on unmigrated DBs too
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        select_cols = "uuid, anchor_id, text, status, notes, position, followup_config"
        if "description" in cols:
            select_cols += ", description"
        if "context_subject" in cols:
            select_cols += ", context_subject"

        task_rows = conn.execute(
            f"SELECT {select_cols} FROM tasks WHERE plan_date=? ORDER BY anchor_id, position",
            (date,),
        ).fetchall()

        anchors: dict = {}
        for row in task_rows:
            aid = row["anchor_id"]
            if aid not in anchors:
                anchors[aid] = {"tasks": [], "notes": row["notes"]}
            anchors[aid]["tasks"].append(_row_to_task(row))

        # Populate dependency fields from the dependencies table
        all_uuids = [t["id"] for a in anchors.values() for t in a["tasks"] if t["id"]]
        if all_uuids:
            try:
                placeholders = ",".join("?" for _ in all_uuids)
                dep_rows = conn.execute(
                    f"SELECT blocker_id, blocked_id FROM dependencies "
                    f"WHERE blocker_type='task' AND blocked_type='task' "
                    f"AND (blocker_id IN ({placeholders}) OR blocked_id IN ({placeholders}))",
                    all_uuids + all_uuids,
                ).fetchall()
                blocked_by_map: dict[str, list] = {}
                blocks_map: dict[str, list] = {}
                for dep in dep_rows:
                    blocked_by_map.setdefault(dep["blocked_id"], []).append(dep["blocker_id"])
                    blocks_map.setdefault(dep["blocker_id"], []).append(dep["blocked_id"])
                for anchor_data in anchors.values():
                    for task in anchor_data["tasks"]:
                        task["blocked_by"] = blocked_by_map.get(task["id"], [])
                        task["blocks"] = blocks_map.get(task["id"], [])
            except sqlite3.OperationalError as e:
                logger.warning("dependencies query failed: %s", e)

        ack_rows = conn.execute(
            "SELECT anchor_id, acknowledged_at FROM acknowledgements WHERE plan_date=?", (date,)
        ).fetchall()
        acknowledgements = {r["anchor_id"]: r["acknowledged_at"] for r in ack_rows}

        check_in_rows = conn.execute(
            "SELECT * FROM check_ins WHERE plan_date=? ORDER BY timestamp", (date,)
        ).fetchall()
        check_in_log = [dict(r) for r in check_in_rows]

        return {"date": date, "anchors": anchors,
                "acknowledgements": acknowledgements, "check_in_log": check_in_log}


def upsert_tasks(
    db_path: Path, date: str, anchor_id: str,
    tasks: list[dict], notes: str = "",
) -> list[dict]:
    """Add or update tasks for (date, anchor_id). Never deletes implicitly.
    Each task: {id?, text?, status?, followup_config?}.
    - With id: update that task (preserves text/status if not provided).
    - Without id but with text: create new task with fresh UUID.
    Plain strings accepted for backward compat (creates new tasks).
    Returns the full task list for this anchor after changes."""
    task_dicts = [
        {"text": t, "status": "pending"} if isinstance(t, str) else t
        for t in tasks
    ]
    with get_db(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO plans (date) VALUES (?)", (date,))

        existing_by_uuid: dict[str, dict] = {}
        for row in conn.execute(
            "SELECT uuid, text, status, followup_config FROM tasks "
            "WHERE plan_date=? AND anchor_id=? AND uuid IS NOT NULL",
            (date, anchor_id),
        ):
            existing_by_uuid[row["uuid"]] = dict(row)

        for task in task_dicts:
            uid = task.get("id") or ""
            text = task.get("text")
            status = task.get("status")
            fc = task.get("followup_config")
            fc_json = json.dumps(fc) if fc is not None else None

            if uid:
                # Update existing task by UUID
                existing = existing_by_uuid.get(uid)
                if not existing:
                    # Check if UUID exists in another anchor/date
                    row = conn.execute(
                        "SELECT text, status FROM tasks WHERE uuid=?", (uid,)
                    ).fetchone()
                    if not row:
                        raise ValueError(f"Task UUID {uid} not found")
                    existing = dict(row)
                text = text or existing["text"]
                status = status or existing.get("status") or "pending"
                conn.execute(
                    "UPDATE tasks SET plan_date=?, anchor_id=?, text=?, status=?, "
                    "followup_config=?, notes=? WHERE uuid=?",
                    (date, anchor_id, text, status, fc_json, notes, uid),
                )
            else:
                # New task — must have text
                if not text:
                    raise ValueError("New tasks must have 'text'")
                uid = str(uuid.uuid4())
                status = status or "pending"
                context_subject = task.get("context_subject")
                max_pos = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM tasks "
                    "WHERE plan_date=? AND anchor_id=?",
                    (date, anchor_id),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO tasks (uuid, plan_date, anchor_id, position, text, status, "
                    "followup_config, notes, context_subject) VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, date, anchor_id, max_pos + 1, text, status, fc_json, notes, context_subject),
                )

        # Return ALL tasks for this anchor (including untouched ones)
        all_rows = conn.execute(
            "SELECT uuid, text, status, position, followup_config, description, context_subject "
            "FROM tasks WHERE plan_date=? AND anchor_id=? ORDER BY position",
            (date, anchor_id),
        ).fetchall()
        return [_row_to_task(r) for r in all_rows]


def patch_task_fields(db_path: Path, task_uuid: str, fields: dict) -> dict | None:
    """Update allowed fields on a task. Returns updated task dict or None if not found."""
    allowed = {"text", "status", "position", "followup_config", "description", "context_subject", "plan_date", "anchor_id"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None
    # JSON-encode followup_config before writing
    if "followup_config" in updates:
        fc = updates["followup_config"]
        updates["followup_config"] = json.dumps(fc) if fc is not None else None
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with get_db(db_path) as conn:
        conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE uuid=?",
            (*updates.values(), task_uuid),
        )
        row = conn.execute(
            "SELECT uuid, text, status, position, followup_config, description, context_subject FROM tasks WHERE uuid=?",
            (task_uuid,),
        ).fetchone()
    if not row:
        return None
    return _row_to_task(row)


def get_task_by_uuid(db_path: Path, task_uuid: str) -> dict | None:
    """Get a single task by UUID."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT uuid, plan_date, anchor_id, text, status, position, followup_config, description, context_subject "
            "FROM tasks WHERE uuid=?", (task_uuid,)
        ).fetchone()
    if not row:
        return None
    return _row_to_task(row, include_schedule=True)


def delete_task_by_uuid(db_path: Path, task_uuid: str) -> None:
    """Delete a task and its related data."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM subtasks WHERE task_id=?", (task_uuid,))
        conn.execute("DELETE FROM links WHERE parent_type='tasks' AND parent_id=?", (task_uuid,))
        conn.execute("DELETE FROM dependencies WHERE (blocker_type='task' AND blocker_id=?) OR (blocked_type='task' AND blocked_id=?)", (task_uuid, task_uuid))
        conn.execute("DELETE FROM milestone_tasks WHERE task_id=?", (task_uuid,))
        conn.execute("DELETE FROM followup_state WHERE task_id=?", (task_uuid,))
        conn.execute("DELETE FROM tasks WHERE uuid=?", (task_uuid,))


def move_task_atomic(
    db_path: Path, task_uuid: str, date: str | None, anchor_id: str | None,
    position: int | None = None,
) -> None:
    """Atomically move a task to a different date/anchor, or unschedule (both None)."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT plan_date FROM tasks WHERE uuid=?", (task_uuid,)
        ).fetchone()
        if not row:
            raise ValueError(f"Task {task_uuid} not found")
        if date is None or anchor_id is None:
            # Unschedule — move to backlog
            conn.execute(
                "UPDATE tasks SET plan_date=NULL, anchor_id=NULL, position=0 WHERE uuid=?",
                (task_uuid,),
            )
            return
        conn.execute("INSERT OR IGNORE INTO plans (date) VALUES (?)", (date,))
        if position is None:
            max_pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM tasks WHERE plan_date=? AND anchor_id=?",
                (date, anchor_id),
            ).fetchone()[0]
            position = max_pos + 1
        conn.execute(
            "UPDATE tasks SET plan_date=?, anchor_id=?, position=? WHERE uuid=?",
            (date, anchor_id, position, task_uuid),
        )


def add_dependency(db_path: Path, blocker_type: str, blocker_id: str,
                   blocked_type: str, blocked_id: str) -> int:
    """Add a dependency. Returns the new row id."""
    with get_db(db_path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO dependencies (blocker_type, blocker_id, blocked_type, blocked_id)"
            " VALUES (?,?,?,?)",
            (blocker_type, blocker_id, blocked_type, blocked_id),
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM dependencies WHERE blocker_type=? AND blocker_id=? AND blocked_type=? AND blocked_id=?",
            (blocker_type, blocker_id, blocked_type, blocked_id),
        ).fetchone()
        return row["id"]


def remove_dependency(db_path: Path, dep_id: int) -> None:
    """Remove a dependency by id."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM dependencies WHERE id=?", (dep_id,))


def get_dependencies_for(db_path: Path, entity_type: str, entity_id: str) -> dict:
    """Return {"blocks": [...], "blocked_by": [...]} for an entity.
    Each item: {"id": dep_id, "type": blocker/blocked type, "entity_id": the other entity's id}"""
    with get_db(db_path) as conn:
        blocker_rows = conn.execute(
            "SELECT id, blocked_type, blocked_id FROM dependencies WHERE blocker_type=? AND blocker_id=?",
            (entity_type, entity_id),
        ).fetchall()
        blocked_rows = conn.execute(
            "SELECT id, blocker_type, blocker_id FROM dependencies WHERE blocked_type=? AND blocked_id=?",
            (entity_type, entity_id),
        ).fetchall()
    blocks = [{"id": r["id"], "type": r["blocked_type"], "entity_id": r["blocked_id"]}
              for r in blocker_rows]
    blocked_by = [{"id": r["id"], "type": r["blocker_type"], "entity_id": r["blocker_id"]}
                  for r in blocked_rows]
    return {"blocks": blocks, "blocked_by": blocked_by}


def get_full_task_dependencies(db_path: Path, task_uuid: str) -> dict:
    """Get all dependencies for a task, regardless of what day the related tasks are on."""
    with get_db(db_path) as conn:
        blocks = conn.execute(
            "SELECT blocked_type, blocked_id FROM dependencies "
            "WHERE blocker_type='task' AND blocker_id=?",
            (task_uuid,),
        ).fetchall()
        blocked_by = conn.execute(
            "SELECT blocker_type, blocker_id FROM dependencies "
            "WHERE blocked_type='task' AND blocked_id=?",
            (task_uuid,),
        ).fetchall()
    return {
        "blocks": [{"type": r["blocked_type"], "id": r["blocked_id"]} for r in blocks],
        "blocked_by": [{"type": r["blocker_type"], "id": r["blocker_id"]} for r in blocked_by],
    }


def add_task_dependency(db_path: Path, task_id: str, blocked_by_id: str) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO task_dependencies (task_id, blocked_by_id) VALUES (?,?)",
            (task_id, blocked_by_id),
        )


def remove_task_dependency(db_path: Path, task_id: str, blocked_by_id: str) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "DELETE FROM task_dependencies WHERE task_id=? AND blocked_by_id=?",
            (task_id, blocked_by_id),
        )


def get_subtasks(db_path: Path, task_id: str) -> list[dict]:
    """Return subtasks ordered by position."""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT id, task_id, text, done, position FROM subtasks WHERE task_id=? ORDER BY position",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_subtask(db_path: Path, task_id: str, text: str, position: int) -> dict:
    """Create a subtask. Returns the new subtask dict."""
    with get_db(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO subtasks (task_id, text, done, position) VALUES (?,?,0,?)",
            (task_id, text, position),
        )
        row_id = cur.lastrowid
        row = conn.execute(
            "SELECT id, task_id, text, done, position FROM subtasks WHERE id=?", (row_id,)
        ).fetchone()
    return dict(row)


def update_subtask(db_path: Path, subtask_id: int, **fields) -> None:
    """Update text, done, and/or position on a subtask. Only update provided fields."""
    allowed = {"text", "done", "position"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with get_db(db_path) as conn:
        conn.execute(
            f"UPDATE subtasks SET {set_clause} WHERE id=?",
            (*updates.values(), subtask_id),
        )


def delete_subtask(db_path: Path, subtask_id: int) -> None:
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM subtasks WHERE id=?", (subtask_id,))


def reorder_subtasks(db_path: Path, task_id: str, id_order: list[int]) -> None:
    """Set position of each subtask based on its index in id_order."""
    with get_db(db_path) as conn:
        for pos, subtask_id in enumerate(id_order):
            conn.execute(
                "UPDATE subtasks SET position=? WHERE id=? AND task_id=?",
                (pos, subtask_id, task_id),
            )


def get_links(db_path: Path, parent_type: str, parent_id: str) -> list[dict]:
    """Return links for a parent entity."""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT id, parent_type, parent_id, url, label, category, created_at "
            "FROM links WHERE parent_type=? AND parent_id=? ORDER BY id",
            (parent_type, parent_id),
        ).fetchall()
    return [dict(r) for r in rows]


def create_link(db_path: Path, parent_type: str, parent_id: str,
                url: str, label: str | None, category: str) -> dict:
    """Create a link. Returns the new link dict."""
    with get_db(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO links (parent_type, parent_id, url, label, category) VALUES (?,?,?,?,?)",
            (parent_type, parent_id, url, label, category),
        )
        row_id = cur.lastrowid
        row = conn.execute(
            "SELECT id, parent_type, parent_id, url, label, category, created_at FROM links WHERE id=?",
            (row_id,),
        ).fetchone()
    return dict(row)


def delete_link(db_path: Path, link_id: int) -> None:
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM links WHERE id=?", (link_id,))


def upsert_context_entry(db_path: Path, subject: str, body: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO context_entries (subject, body, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(subject) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at
        """, (subject, body, now))


def get_context_entries(db_path: Path, prefix: str | None = None,
                        top_level_only: bool = False) -> list[dict]:
    with get_db(db_path) as conn:
        if prefix:
            rows = conn.execute(
                "SELECT subject, body, updated_at FROM context_entries"
                " WHERE subject = ? OR subject LIKE ? ORDER BY subject",
                (prefix, prefix + "/%")
            ).fetchall()
        elif top_level_only:
            rows = conn.execute(
                "SELECT subject, body, updated_at FROM context_entries"
                " WHERE subject NOT LIKE '%/%' ORDER BY subject"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT subject, body, updated_at FROM context_entries ORDER BY subject"
            ).fetchall()
        return [dict(r) for r in rows]


def delete_context_entry(db_path: Path, subject: str) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "DELETE FROM context_entries WHERE subject = ? OR subject LIKE ?",
            (subject, subject + "/%")
        )


def rename_context_subject(db_path: Path, old_subject: str, new_subject: str) -> None:
    """Rename a subject and cascade to all children."""
    with get_db(db_path) as conn:
        # Temporarily disable FK checks so we can update both tables atomically
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "UPDATE context_entries SET subject = ? WHERE subject = ?",
            (new_subject, old_subject)
        )
        children = conn.execute(
            "SELECT subject FROM context_entries WHERE subject LIKE ?",
            (old_subject + "/%",)
        ).fetchall()
        for row in children:
            new_child = new_subject + row["subject"][len(old_subject):]
            conn.execute(
                "UPDATE context_entries SET subject = ? WHERE subject = ?",
                (new_child, row["subject"])
            )
        # cascade milestone context_subject (exact match)
        conn.execute(
            "UPDATE milestones SET context_subject=? WHERE context_subject=?",
            (new_subject, old_subject),
        )
        # cascade milestone context_subject (child subjects)
        for row in children:
            new_child = new_subject + row["subject"][len(old_subject):]
            conn.execute(
                "UPDATE milestones SET context_subject=? WHERE context_subject=?",
                (new_child, row["subject"]),
            )
        # cascade tasks.context_subject (exact match)
        conn.execute(
            "UPDATE tasks SET context_subject=? WHERE context_subject=?",
            (new_subject, old_subject),
        )
        # cascade tasks.context_subject (child subjects)
        for row in children:
            new_child = new_subject + row["subject"][len(old_subject):]
            conn.execute(
                "UPDATE tasks SET context_subject=? WHERE context_subject=?",
                (new_child, row["subject"]),
            )
        conn.execute("PRAGMA foreign_keys = ON")


def list_plan_dates(db_path: Path) -> list[str]:
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT date FROM plans ORDER BY date DESC").fetchall()
        return [r["date"] for r in rows]


def patch_anchor(db_path: Path, anchor_id: str, **fields) -> None:
    """Update only the provided fields on an existing anchor."""
    allowed = {"name", "time", "duration_minutes", "flexibility", "strictness", "color"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    with get_db(db_path) as conn:
        row = conn.execute("SELECT * FROM anchors WHERE id=?", (anchor_id,)).fetchone()
        if not row:
            raise ValueError(f"Anchor {anchor_id!r} not found")
        anchor = dict(row)
    anchor.update(updates)
    upsert_anchor(db_path, anchor)


def insert_conversation_turn(db_path: Path, role: str, body: str) -> None:
    """Append one turn to conversation history. role is 'user' or 'assistant'."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO conversation_history (role, body) VALUES (?, ?)",
            (role, body),
        )


def get_recent_history(db_path: Path, n: int = 5) -> list[dict]:
    """Return the last n exchange pairs (up to 2*n rows) in chronological order."""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT role, body, ts FROM conversation_history ORDER BY id DESC LIMIT ?",
            (n * 2,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def clear_session_state(db_path: Path, session_id: str) -> None:
    """Delete all staging mutations and orchestrator conversation rows for a session."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM staging_mutations WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM orchestrator_conversation WHERE session_id=?", (session_id,))


def insert_orchestrator_turn(db_path: Path, session_id: str,
                              role: str, body: str, round_num: int) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO orchestrator_conversation (session_id, role, body, round_num)"
            " VALUES (?, ?, ?, ?)",
            (session_id, role, body, round_num),
        )


def get_orchestrator_conversation(db_path: Path, session_id: str) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT role, body, round_num, ts FROM orchestrator_conversation"
            " WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_staging_mutation(db_path: Path, session_id: str, id: str,
                             type: str, description: str, params_json: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO staging_mutations (id, session_id, type, description, params_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                description=excluded.description,
                params_json=excluded.params_json,
                updated_at=excluded.updated_at
        """, (id, session_id, type, description, params_json, now, now))


def get_staging_mutations(db_path: Path, session_id: str) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT id, session_id, type, description, params_json, created_at, updated_at"
            " FROM staging_mutations WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def log_stage(db_path: Path, session_id: str, stage: str,
              prompt: str, response: str, error: str | None = None) -> None:
    """Append one pipeline stage to the invocation log; prune to last 10 sessions."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO invocation_log (session_id, stage, prompt, response, error, ts)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, stage, prompt, response, error, now),
        )
        conn.execute("""
            DELETE FROM invocation_log
            WHERE session_id NOT IN (
                SELECT session_id FROM (
                    SELECT session_id, MAX(ts) AS latest
                    FROM invocation_log
                    GROUP BY session_id
                    ORDER BY latest DESC
                    LIMIT 10
                )
            )
        """)


def get_invocation_log(db_path: Path, n: int = 5) -> list[dict]:
    """Return all log entries for the last n sessions, oldest first."""
    with get_db(db_path) as conn:
        rows = conn.execute("""
            SELECT id, session_id, stage, prompt, response, error, ts
            FROM invocation_log
            WHERE session_id IN (
                SELECT session_id FROM (
                    SELECT session_id, MAX(ts) AS latest
                    FROM invocation_log
                    GROUP BY session_id
                    ORDER BY latest DESC
                    LIMIT ?
                )
            )
            ORDER BY id
        """, (n,)).fetchall()
    return [dict(r) for r in rows]


def get_last_bot_activity(db_path: Path) -> dict | None:
    """Return the most recent invocation_log entry."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT stage, response, error, ts FROM invocation_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {"stage": row["stage"], "response": row["response"][:200] if row["response"] else None,
            "error": row["error"], "ts": row["ts"]}


def insert_check_in(db_path: Path, date: str, anchor_id: str,
                    accomplished: str, current_status: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO check_ins (plan_date, anchor_id, type, timestamp, accomplished, current_status)"
            " VALUES (?, ?, 'user_checkin', ?, ?, ?)",
            (date, anchor_id, now, accomplished, current_status),
        )


def _derive_milestone_status(statuses: list[str]) -> str:
    if not statuses:
        return 'pending'
    if all(s == 'done' for s in statuses):
        return 'done'
    if any(s == 'blocked' for s in statuses) and not any(s == 'in_progress' for s in statuses):
        return 'blocked'
    if any(s in ('in_progress', 'done') for s in statuses):
        return 'in_progress'
    return 'pending'


def create_milestone(
    db_path: Path, context_subject: str, name: str,
    description: str | None = None, target_date: str | None = None,
    color: str | None = None,
) -> dict:
    mid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db(db_path) as conn:
        # Check if color column exists
        cols = [r[1] for r in conn.execute("PRAGMA table_info(milestones)").fetchall()]
        if "color" in cols:
            conn.execute(
                "INSERT INTO milestones (id, context_subject, name, description, target_date, color, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (mid, context_subject, name, description, target_date, color, now, now),
            )
        else:
            conn.execute(
                "INSERT INTO milestones (id, context_subject, name, description, target_date, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (mid, context_subject, name, description, target_date, now, now),
            )
    return {
        "id": mid, "context_subject": context_subject, "name": name,
        "description": description, "target_date": target_date,
        "color": color,
        "status": "pending", "status_override": False,
        "created_at": now, "updated_at": now,
        "task_count": 0, "done_count": 0, "task_ids": [], "tasks": [],
    }


def get_milestones(db_path: Path, context_subject: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        if context_subject is not None:
            rows = conn.execute(
                "SELECT * FROM milestones WHERE context_subject=? ORDER BY created_at",
                (context_subject,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM milestones ORDER BY context_subject, created_at"
            ).fetchall()

        if not rows:
            return []

        ids = [m["id"] for m in rows]
        ph = ",".join("?" for _ in ids)
        links = conn.execute(
            f"SELECT mt.milestone_id, mt.task_id, "
            f"COALESCE(t.status, 'pending') AS task_status, "
            f"t.text AS task_text, t.plan_date, t.anchor_id "
            f"FROM milestone_tasks mt "
            f"LEFT JOIN tasks t ON t.uuid = mt.task_id "
            f"WHERE mt.milestone_id IN ({ph})",
            ids,
        ).fetchall()

    task_ids_map: dict = defaultdict(list)
    tasks_map: dict = defaultdict(list)
    statuses_map: dict = defaultdict(list)
    for row in links:
        mid = row["milestone_id"]
        task_ids_map[mid].append(row["task_id"])
        statuses_map[mid].append(row["task_status"])
        tasks_map[mid].append({
            "id": row["task_id"], "text": row["task_text"],
            "status": row["task_status"],
            "plan_date": row["plan_date"], "anchor_id": row["anchor_id"],
        })

    result = []
    for m in rows:
        mid = m["id"]
        statuses = statuses_map[mid]
        result.append({
            "id": mid,
            "context_subject": m["context_subject"],
            "name": m["name"],
            "description": m["description"],
            "target_date": m["target_date"],
            "color": m["color"] if "color" in m.keys() else None,
            "status": m["status"] if m["status_override"] else _derive_milestone_status(statuses),
            "status_override": bool(m["status_override"]),
            "created_at": m["created_at"],
            "updated_at": m["updated_at"],
            "task_count": len(statuses),
            "done_count": sum(1 for s in statuses if s == "done"),
            "task_ids": task_ids_map[mid],
            "tasks": tasks_map[mid],
        })
    return result


def patch_milestone(db_path: Path, milestone_id: str, fields: dict) -> dict | None:
    allowed = {"name", "description", "target_date", "color"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "status" in fields:
        updates["status"] = fields["status"]
        updates["status_override"] = 1
    if not updates:
        return None
    updates["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with get_db(db_path) as conn:
        cur = conn.execute(
            f"UPDATE milestones SET {set_clause} WHERE id=?",
            (*updates.values(), milestone_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT context_subject FROM milestones WHERE id=?", (milestone_id,)
        ).fetchone()
    subject = row["context_subject"]
    return next((m for m in get_milestones(db_path, subject) if m["id"] == milestone_id), None)


def delete_milestone(db_path: Path, milestone_id: str) -> None:
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM milestones WHERE id=?", (milestone_id,))


def link_milestone_task(db_path: Path, milestone_id: str, task_id: str) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO milestone_tasks (milestone_id, task_id) VALUES (?,?)",
            (milestone_id, task_id),
        )


def unlink_milestone_task(db_path: Path, milestone_id: str, task_id: str) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "DELETE FROM milestone_tasks WHERE milestone_id=? AND task_id=?",
            (milestone_id, task_id),
        )


def init_followup_state(
    db_path: Path, date: str, anchor_id: str, task_id: str, now: datetime,
) -> None:
    """INSERT OR IGNORE — idempotent, won't reset existing state."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO followup_state "
            "(date, anchor_id, task_id, sequence_started_at) VALUES (?,?,?,?)",
            (date, anchor_id, task_id, now.isoformat()),
        )


def get_active_followup_states(db_path: Path, date: str) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM followup_state WHERE date=? AND completed=0 ORDER BY id",
            (date,),
        ).fetchall()
    return [dict(r) for r in rows]


def acknowledge_followup(db_path: Path, date: str, anchor_id: str, now: datetime) -> None:
    """Set acknowledged_at on all unacked rows for this anchor today."""
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE followup_state SET acknowledged_at=? "
            "WHERE date=? AND anchor_id=? AND acknowledged_at IS NULL AND completed=0",
            (now.isoformat(), date, anchor_id),
        )


def record_ping(db_path: Path, row_id: int, phase: str, now: datetime) -> None:
    """Increment pre_ack_pings_sent or post_ack_pings_sent and update last_ping_at."""
    col = "pre_ack_pings_sent" if phase == "pre" else "post_ack_pings_sent"
    with get_db(db_path) as conn:
        conn.execute(
            f"UPDATE followup_state SET {col}={col}+1, last_ping_at=? WHERE id=?",
            (now.isoformat(), row_id),
        )


def mark_followup_completed(db_path: Path, task_id: str, date: str) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE followup_state SET completed=1 WHERE task_id=? AND date=?",
            (task_id, date),
        )


def resolve_followup_config(db_path: Path, anchor_id: str, task_id: str) -> dict | None:
    """Return resolved FollowupConfig: task overrides anchor, None if neither enabled."""
    with get_db(db_path) as conn:
        task_row = conn.execute(
            "SELECT followup_config FROM tasks WHERE uuid=?", (task_id,)
        ).fetchone()
        anchor_row = conn.execute(
            "SELECT followup_config FROM anchors WHERE id=?", (anchor_id,)
        ).fetchone()
    task_fc = json.loads(task_row["followup_config"]) if task_row and task_row["followup_config"] else None
    anchor_fc = json.loads(anchor_row["followup_config"]) if anchor_row and anchor_row["followup_config"] else None
    config = task_fc or anchor_fc
    if not config or not config.get("enabled"):
        return None
    return config


def create_unscheduled_task(
    db_path: Path, text: str, description: str | None = None,
    status: str = "pending", context_subject: str | None = None,
) -> dict:
    """Create a task with no plan_date or anchor_id (backlog task)."""
    task_uuid = str(uuid.uuid4())
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO tasks (uuid, plan_date, anchor_id, text, status, description, context_subject) "
            "VALUES (?,NULL,NULL,?,?,?,?)",
            (task_uuid, text, status, description, context_subject),
        )
        row = conn.execute(
            "SELECT uuid, text, status, position, followup_config, description, context_subject "
            "FROM tasks WHERE uuid=?", (task_uuid,)
        ).fetchone()
    return _row_to_task(row)


def get_unscheduled_tasks(db_path: Path) -> list[dict]:
    """Get all tasks with no plan_date (backlog), with context_subject."""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT uuid, text, status, position, followup_config, description, context_subject "
            "FROM tasks WHERE plan_date IS NULL ORDER BY position, id"
        ).fetchall()
    return [_row_to_task(r) for r in rows]


def get_all_tasks(db_path: Path) -> list[dict]:
    """Get ALL tasks (scheduled + unscheduled) with schedule info. For kanban board."""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT uuid, text, status, position, followup_config, description, "
            "context_subject, plan_date, anchor_id "
            "FROM tasks ORDER BY plan_date DESC NULLS LAST, position"
        ).fetchall()
    return [_row_to_task(r, include_schedule=True) for r in rows]


def search_entities(db_path: Path, query: str, entity_type: str = "all") -> list[dict]:
    """Search tasks and/or milestones by text. Returns [{id, label, sublabel, type}]."""
    results = []
    q = f"%{query}%"
    with get_db(db_path) as conn:
        if entity_type in ("all", "task"):
            rows = conn.execute(
                "SELECT uuid, text, anchor_id, plan_date FROM tasks WHERE text LIKE ? ORDER BY plan_date DESC LIMIT 20",
                (q,),
            ).fetchall()
            for r in rows:
                results.append({
                    "id": r["uuid"], "label": r["text"],
                    "sublabel": f"task · {r['anchor_id']} · {r['plan_date']}",
                    "type": "task",
                })
        if entity_type in ("all", "milestone"):
            rows = conn.execute(
                "SELECT id, name, context_subject FROM milestones WHERE name LIKE ? ORDER BY name LIMIT 20",
                (q,),
            ).fetchall()
            for r in rows:
                results.append({
                    "id": r["id"], "label": r["name"],
                    "sublabel": f"milestone · {r['context_subject']}",
                    "type": "milestone",
                })
    return results


# ---------------------------------------------------------------------------
# Task-context linking
# ---------------------------------------------------------------------------


def get_context_tasks(db_path: Path, subject: str) -> list[dict]:
    """Return tasks linked to a context subject (uses context_subject column).
    Returns [{id, text, status, plan_date, anchor_id}] — 'id' matches _row_to_task convention."""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT uuid, text, status, plan_date, anchor_id "
            "FROM tasks WHERE context_subject=? ORDER BY plan_date DESC",
            (subject,),
        ).fetchall()
    return [{"id": r["uuid"], "text": r["text"], "status": r["status"],
             "plan_date": r["plan_date"], "anchor_id": r["anchor_id"]} for r in rows]


# ---------------------------------------------------------------------------
# Multi-turn session management
# ---------------------------------------------------------------------------

_VALID_SESSION_STATES = {"active", "waiting_user", "closed"}


def create_session(db_path: Path, chat_id: str, max_turns: int = 10) -> str:
    """Create a new session, closing any existing active session for this chat."""
    sid = str(uuid.uuid4())
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET state = 'closed' "
            "WHERE chat_id = ? AND state IN ('active', 'waiting_user')",
            (chat_id,),
        )
        conn.execute(
            "INSERT INTO sessions (id, chat_id, state, max_turns) VALUES (?, ?, 'active', ?)",
            (sid, chat_id, max_turns),
        )
    return sid


def get_active_session(db_path: Path, chat_id: str) -> dict | None:
    """Get the active or waiting session for a chat, or None."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE chat_id = ? AND state IN ('active', 'waiting_user') "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
    return dict(row) if row else None


def update_session_state(db_path: Path, session_id: str, state: str) -> None:
    """Update session state. State must be one of: active, waiting_user, closed."""
    if state not in _VALID_SESSION_STATES:
        raise ValueError(f"Invalid session state: {state!r}. Must be one of {_VALID_SESSION_STATES}")
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET state = ?, last_activity = CURRENT_TIMESTAMP WHERE id = ?",
            (state, session_id),
        )


def update_session_activity(db_path: Path, session_id: str, turn_count: int) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET turn_count = ?, last_activity = CURRENT_TIMESTAMP WHERE id = ?",
            (turn_count, session_id),
        )


def close_session(db_path: Path, session_id: str, summary: str | None = None) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET state = 'closed', summary = ?, last_activity = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (summary, session_id),
        )


def get_stale_sessions(db_path: Path, timeout_minutes: int = 15) -> list[dict]:
    """Find sessions idle longer than timeout_minutes."""
    interval = f"-{int(timeout_minutes)} minutes"
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE state IN ('active', 'waiting_user') "
            "AND last_activity < datetime('now', ?)",
            (interval,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Kanban columns
# ---------------------------------------------------------------------------

def seed_kanban_columns(db_path: Path) -> None:
    """Create default kanban columns if none exist."""
    with get_db(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM kanban_columns").fetchone()[0]
        if count > 0:
            return
        defaults = [
            ("col_backlog", "Backlog", 0, None,
             json.dumps({"plan_date": None, "status": "pending"}),
             json.dumps({"set_status": "pending", "unschedule": True})),
            ("col_pending", "Pending", 1, "#3b82f6",
             json.dumps({"status": "pending", "plan_date": "not_null"}),
             json.dumps({"set_status": "pending", "prompt_schedule": True})),
            ("col_in_progress", "In Progress", 2, "#f59e0b",
             json.dumps({"status": "in_progress"}),
             json.dumps({"set_status": "in_progress"})),
            ("col_done", "Done", 3, "#22c55e",
             json.dumps({"status": "done"}),
             json.dumps({"set_status": "done"})),
            ("col_skipped", "Skipped", 4, "#94a3b8",
             json.dumps({"status": "skipped"}),
             json.dumps({"set_status": "skipped"})),
            ("col_blocked", "Blocked", 5, "#ef4444",
             json.dumps({"status": "blocked"}),
             json.dumps({"set_status": "blocked"})),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO kanban_columns (id, name, position, color, match_rules, entry_rules) "
            "VALUES (?,?,?,?,?,?)",
            defaults,
        )


def migrate_backlog_column(db_path: Path) -> None:
    """Tighten Backlog match_rules and add unschedule entry_rule (fixes drag-drop)."""
    new_match = json.dumps({"plan_date": None, "status": "pending"})
    new_entry = json.dumps({"set_status": "pending", "unschedule": True})
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE kanban_columns SET match_rules=?, entry_rules=? WHERE id='col_backlog'",
            (new_match, new_entry),
        )


def get_kanban_columns(db_path: Path, user_id: str | None = None) -> list[dict]:
    """Get columns visible to user: built-in (created_by IS NULL) + user's own."""
    with get_db(db_path) as conn:
        if user_id:
            rows = conn.execute(
                "SELECT * FROM kanban_columns WHERE created_by IS NULL OR created_by=? ORDER BY position",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM kanban_columns WHERE created_by IS NULL ORDER BY position"
            ).fetchall()
    return [
        {"id": r["id"], "name": r["name"], "position": r["position"],
         "color": r["color"],
         "match_rules": json.loads(r["match_rules"]),
         "entry_rules": json.loads(r["entry_rules"]),
         "created_by": r["created_by"]}
        for r in rows
    ]


def create_kanban_column(
    db_path: Path, name: str, position: int, color: str | None,
    match_rules: dict, entry_rules: dict, created_by: str,
) -> dict:
    col_id = str(uuid.uuid4())
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO kanban_columns (id, name, position, color, match_rules, entry_rules, created_by) "
            "VALUES (?,?,?,?,?,?,?)",
            (col_id, name, position, color, json.dumps(match_rules), json.dumps(entry_rules), created_by),
        )
    return {"id": col_id, "name": name, "position": position, "color": color,
            "match_rules": match_rules, "entry_rules": entry_rules, "created_by": created_by}


def update_kanban_column(db_path: Path, column_id: str, fields: dict) -> dict | None:
    allowed = {"name", "position", "color", "match_rules", "entry_rules"}
    updates = {}
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("match_rules", "entry_rules"):
            updates[k] = json.dumps(v) if isinstance(v, dict) else v
        else:
            updates[k] = v
    if not updates:
        return None
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with get_db(db_path) as conn:
        conn.execute(f"UPDATE kanban_columns SET {set_clause} WHERE id=?",
                     (*updates.values(), column_id))
        row = conn.execute("SELECT * FROM kanban_columns WHERE id=?", (column_id,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "name": row["name"], "position": row["position"],
            "color": row["color"],
            "match_rules": json.loads(row["match_rules"]),
            "entry_rules": json.loads(row["entry_rules"]),
            "created_by": row["created_by"]}


def delete_kanban_column(db_path: Path, column_id: str) -> None:
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM kanban_columns WHERE id=?", (column_id,))
