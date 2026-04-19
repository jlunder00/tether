"""Async Postgres queries — plans table and related."""
from __future__ import annotations
import uuid as _uuid

import asyncpg


async def upsert_plan(conn: asyncpg.Connection, date: str) -> None:
    await conn.execute(
        """
        INSERT INTO plans (date, user_id)
        VALUES ($1, current_setting('app.current_user_id', true)::uuid)
        ON CONFLICT (date, user_id) DO NOTHING
        """,
        date,
    )


async def get_plan(conn: asyncpg.Connection, date: str) -> dict:
    row = await conn.fetchrow(
        "SELECT date FROM plans WHERE date = $1", date
    )
    if not row:
        return {"date": date, "anchors": {}, "acknowledgements": {}, "check_in_log": []}

    task_rows = await conn.fetch(
        """
        SELECT uuid, anchor_id, text, status, notes, position,
               followup_config, description, context_subject, context_node_id, version
        FROM tasks
        WHERE plan_date = $1
        ORDER BY anchor_id, position
        """,
        date,
    )

    anchors: dict = {}
    for row in task_rows:
        aid = str(row["anchor_id"]) if row["anchor_id"] else None
        if aid not in anchors:
            anchors[aid] = {"tasks": [], "notes": row["notes"]}
        anchors[aid]["tasks"].append(_row_to_task(row))

    all_uuids = [t["id"] for a in anchors.values() for t in a["tasks"] if t["id"]]
    if all_uuids:
        dep_rows = await conn.fetch(
            """
            SELECT blocker_id, blocked_id FROM dependencies
            WHERE blocker_type = 'task' AND blocked_type = 'task'
              AND (blocker_id = ANY($1) OR blocked_id = ANY($1))
            """,
            all_uuids,
        )
        blocked_by_map: dict[str, list] = {}
        blocks_map: dict[str, list] = {}
        for dep in dep_rows:
            blocked_by_map.setdefault(dep["blocked_id"], []).append(dep["blocker_id"])
            blocks_map.setdefault(dep["blocker_id"], []).append(dep["blocked_id"])
        for anchor_data in anchors.values():
            for task in anchor_data["tasks"]:
                task["blocked_by"] = blocked_by_map.get(task["id"], [])
                task["blocks"] = blocks_map.get(task["id"], [])

    ack_rows = await conn.fetch(
        "SELECT anchor_id, acknowledged_at FROM acknowledgements WHERE plan_date = $1",
        date,
    )
    acknowledgements = {str(r["anchor_id"]): r["acknowledged_at"] for r in ack_rows}

    check_in_rows = await conn.fetch(
        "SELECT * FROM check_ins WHERE plan_date = $1 ORDER BY timestamp", date
    )
    check_in_log = [dict(r) for r in check_in_rows]

    return {
        "date": date,
        "anchors": anchors,
        "acknowledgements": acknowledgements,
        "check_in_log": check_in_log,
    }


async def list_plan_dates(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch("SELECT date FROM plans ORDER BY date DESC")
    return [r["date"] for r in rows]


def _row_to_task(row, *, include_schedule: bool = False) -> dict:
    r = dict(row)
    d = {
        "id": str(r["uuid"]) if r.get("uuid") else None,
        "text": r["text"],
        "status": r.get("status") or "pending",
        "position": r.get("position", 0),
        "description": r.get("description"),
        "context_subject": r.get("context_subject"),
        "context_node_id": str(r["context_node_id"]) if r.get("context_node_id") else None,
        "followup_config": r.get("followup_config"),  # asyncpg already deserialises JSONB
        "version": r.get("version", 0),
        "blocks": [],
        "blocked_by": [],
    }
    if include_schedule:
        d["plan_date"] = r.get("plan_date")
        d["anchor_id"] = str(r["anchor_id"]) if r.get("anchor_id") else None
    return d
