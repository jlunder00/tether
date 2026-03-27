from __future__ import annotations
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


def upsert_tasks(db_path: Path, date: str, anchor_id: str,
                 tasks: list[str], notes: str) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "DELETE FROM tasks WHERE plan_date=? AND anchor_id=?", (date, anchor_id)
        )
        for i, text in enumerate(tasks):
            conn.execute(
                "INSERT INTO tasks (plan_date, anchor_id, position, text, notes) VALUES (?,?,?,?,?)",
                (date, anchor_id, i, text, notes)
            )


def upsert_context_entry(db_path: Path, subject: str, body: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT INTO context_entries (subject, body, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(subject) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at
        """, (subject, body, now))


def get_context_entries(db_path: Path) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT subject, body, updated_at FROM context_entries ORDER BY subject"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_context_entry(db_path: Path, subject: str) -> None:
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM context_entries WHERE subject=?", (subject,))


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


def insert_check_in(db_path: Path, date: str, anchor_id: str,
                    accomplished: str, current_status: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO check_ins (plan_date, anchor_id, type, timestamp, accomplished, current_status)"
            " VALUES (?, ?, 'user_checkin', ?, ?, ?)",
            (date, anchor_id, now, accomplished, current_status),
        )
