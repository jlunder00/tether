from __future__ import annotations
import json
import uuid
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
            "SELECT anchor_id, text, notes, position FROM tasks WHERE plan_date=? ORDER BY anchor_id, position",
            (date,)
        ).fetchall()

        anchors: dict = {}
        for row in task_rows:
            aid = row["anchor_id"]
            if aid not in anchors:
                anchors[aid] = {"tasks": [], "notes": row["notes"]}
            anchors[aid]["tasks"].append(row["text"])

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
