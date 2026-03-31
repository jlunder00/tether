from __future__ import annotations
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from db.schema import get_db


def upsert_anchor(db_path: Path, anchor: dict) -> None:
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO anchors (id, name, time, duration_minutes, flexibility, strictness, color, position)
            VALUES (:id, :name, :time, :duration_minutes, :flexibility, :strictness, :color, :position)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, time=excluded.time,
                duration_minutes=excluded.duration_minutes,
                flexibility=excluded.flexibility, strictness=excluded.strictness,
                color=excluded.color, position=excluded.position
        """, anchor)


def get_anchors(db_path: Path) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM anchors ORDER BY position").fetchall()
        return [dict(r) for r in rows]


def upsert_plan(db_path: Path, date: str) -> None:
    with get_db(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO plans (date) VALUES (?)", (date,))


def get_plan(db_path: Path, date: str) -> dict:
    with get_db(db_path) as conn:
        plan_row = conn.execute("SELECT date FROM plans WHERE date=?", (date,)).fetchone()
        if not plan_row:
            return {"date": date, "anchors": {}, "acknowledgements": {}, "check_in_log": []}

        task_rows = conn.execute(
            "SELECT uuid, anchor_id, text, status, notes, position, followup_config "
            "FROM tasks WHERE plan_date=? ORDER BY anchor_id, position",
            (date,)
        ).fetchall()

        anchors: dict = {}
        for row in task_rows:
            aid = row["anchor_id"]
            if aid not in anchors:
                anchors[aid] = {"tasks": [], "notes": row["notes"]}
            fc = row["followup_config"]
            anchors[aid]["tasks"].append({
                "id": row["uuid"],
                "text": row["text"],
                "status": row["status"] or "pending",
                "position": row["position"],
                "followup_config": json.loads(fc) if fc else None,
                "blocks": [],
                "blocked_by": [],
            })

        # Populate dependency fields
        all_uuids = [t["id"] for a in anchors.values() for t in a["tasks"] if t["id"]]
        if all_uuids:
            placeholders = ",".join("?" for _ in all_uuids)
            dep_rows = conn.execute(
                f"SELECT task_id, blocked_by_id FROM task_dependencies "
                f"WHERE task_id IN ({placeholders}) OR blocked_by_id IN ({placeholders})",
                all_uuids + all_uuids,
            ).fetchall()
            blocked_by_map: dict[str, list] = {}
            blocks_map: dict[str, list] = {}
            for dep in dep_rows:
                blocked_by_map.setdefault(dep["task_id"], []).append(dep["blocked_by_id"])
                blocks_map.setdefault(dep["blocked_by_id"], []).append(dep["task_id"])
            for anchor_data in anchors.values():
                for task in anchor_data["tasks"]:
                    task["blocked_by"] = blocked_by_map.get(task["id"], [])
                    task["blocks"] = blocks_map.get(task["id"], [])

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
    """Merge task list for (date, anchor_id). Each task: {id?, text, status?, followup_config?}.
    Accepts plain strings for backward compatibility. Returns list with UUIDs populated."""
    task_dicts = [
        {"text": t, "status": "pending"} if isinstance(t, str) else t
        for t in tasks
    ]
    with get_db(db_path) as conn:
        existing_uuids = {
            row["uuid"]
            for row in conn.execute(
                "SELECT uuid FROM tasks WHERE plan_date=? AND anchor_id=? AND uuid IS NOT NULL",
                (date, anchor_id),
            )
        }
        incoming_uuids = {t["id"] for t in task_dicts if t.get("id")}
        for uid in existing_uuids - incoming_uuids:
            conn.execute("DELETE FROM tasks WHERE uuid=?", (uid,))

        result = []
        for pos, task in enumerate(task_dicts):
            uid = task.get("id") or ""
            status = task.get("status", "pending")
            fc = task.get("followup_config")
            fc_json = json.dumps(fc) if fc is not None else None
            if uid and uid in existing_uuids:
                conn.execute(
                    "UPDATE tasks SET text=?, status=?, position=?, followup_config=?, notes=? "
                    "WHERE uuid=?",
                    (task["text"], status, pos, fc_json, notes, uid),
                )
            else:
                uid = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO tasks (uuid, plan_date, anchor_id, position, text, status, "
                    "followup_config, notes) VALUES (?,?,?,?,?,?,?,?)",
                    (uid, date, anchor_id, pos, task["text"], status, fc_json, notes),
                )
            result.append({
                "id": uid, "text": task["text"], "status": status,
                "position": pos, "followup_config": fc,
                "blocks": [], "blocked_by": [],
            })
        return result


def patch_task_fields(db_path: Path, task_uuid: str, fields: dict) -> dict | None:
    """Update allowed fields on a task. Returns updated task dict or None if not found."""
    allowed = {"text", "status", "position", "followup_config"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with get_db(db_path) as conn:
        conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE uuid=?",
            (*updates.values(), task_uuid),
        )
        row = conn.execute(
            "SELECT uuid, text, status, position, followup_config FROM tasks WHERE uuid=?",
            (task_uuid,),
        ).fetchone()
    if not row:
        return None
    fc = row["followup_config"]
    return {
        "id": row["uuid"], "text": row["text"], "status": row["status"],
        "position": row["position"],
        "followup_config": json.loads(fc) if fc else None,
        "blocks": [], "blocked_by": [],
    }


def move_task_atomic(
    db_path: Path, task_uuid: str, date: str, anchor_id: str, position: int | None = None,
) -> None:
    """Atomically move a task to a different date/anchor."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT plan_date FROM tasks WHERE uuid=?", (task_uuid,)
        ).fetchone()
        if not row:
            raise ValueError(f"Task {task_uuid} not found")
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
) -> dict:
    mid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO milestones (id, context_subject, name, description, target_date, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (mid, context_subject, name, description, target_date, now, now),
        )
    return {
        "id": mid, "context_subject": context_subject, "name": name,
        "description": description, "target_date": target_date,
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
    allowed = {"name", "description", "target_date"}
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
