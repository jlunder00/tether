"""Async Postgres queries — plans table and related."""
from __future__ import annotations
import datetime as _dt
import uuid as _uuid

import asyncpg
from dateutil.rrule import rrulestr as _rrulestr


async def upsert_plan(conn: asyncpg.Connection, date: str) -> None:
    await conn.execute(
        """
        INSERT INTO plans (date, user_id)
        VALUES ($1, current_setting('app.current_user_id', true)::uuid)
        ON CONFLICT (date, user_id) DO NOTHING
        """,
        date,
    )


def _anchor_recurring_occurs_on(rrule_str: str, date_str: str) -> bool:
    """Return True if the rrule fires on the given calendar date (date-only, ignoring time).

    Accepts rrule strings with or without the 'RRULE:' prefix, and with or
    without an embedded DTSTART line.
    """
    target_date = _dt.date.fromisoformat(date_str)
    dtstart = _dt.datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
    window_end = dtstart + _dt.timedelta(days=1)
    rule = _rrulestr(rrule_str, dtstart=dtstart, ignoretz=True)
    occurrences = rule.between(dtstart, window_end, inc=True)
    return len(occurrences) > 0


async def get_plan(conn: asyncpg.Connection, date: str) -> dict:
    row = await conn.fetchrow(
        "SELECT date FROM plans WHERE date = $1", date
    )
    if not row:
        return {"date": date, "anchors": {}, "acknowledgements": {}, "check_in_log": []}

    task_rows = await conn.fetch(
        """
        SELECT uuid, anchor_id, text, status, notes, position,
               followup_config, description, context_subject, context_node_id, motif, version
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

    # Expand anchor-recurring masters for this date (on-demand, RLS scoped)
    master_rows = await conn.fetch(
        """
        SELECT uuid, anchor_id, text, status, notes, position,
               rrule, color, context_subject, context_node_id,
               followup_config, description, motif, version, exdates
        FROM tasks
        WHERE anchor_id IS NOT NULL
          AND rrule IS NOT NULL
          AND plan_date IS NULL
          AND recurrence_id IS NULL
          AND start_time IS NULL
          AND (source_status IS NULL OR source_status != 'cancelled')
        ORDER BY anchor_id, position
        """,
    )
    for master in master_rows:
        rrule_str = master["rrule"]
        if not _anchor_recurring_occurs_on(rrule_str, date):
            continue
        # Check exdates — stored as plain ISO date strings for anchor-recurring tasks
        exdates = list(master["exdates"] or [])
        if date in exdates:
            continue
        # Skip if there's already an exception occurrence row for this date
        exception = await conn.fetchrow(
            "SELECT uuid FROM tasks WHERE recurrence_id = $1 AND plan_date = $2",
            str(master["uuid"]), date,
        )
        if exception:
            continue  # Exception row already picked up by plan_date query above
        aid = str(master["anchor_id"])
        if aid not in anchors:
            anchors[aid] = {"tasks": [], "notes": master["notes"]}
        anchors[aid]["tasks"].append({
            "id": str(master["uuid"]),
            "text": master["text"],
            "status": master["status"] or "pending",
            "position": master["position"] or 0,
            "description": master["description"],
            "context_subject": master["context_subject"],
            "context_node_id": str(master["context_node_id"]) if master["context_node_id"] else None,
            "followup_config": master["followup_config"],
            "motif": master["motif"] or "anchor",
            "version": master["version"] or 0,
            "anchor_id": aid,
            "plan_date": date,
            "rrule": rrule_str,
            "color": master["color"],
            "is_recurring_master": True,
            "blocks": [],
            "blocked_by": [],
        })

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
        "motif": r.get("motif", "anchor"),
        "version": r.get("version", 0),
        "blocks": [],
        "blocked_by": [],
    }
    if include_schedule:
        d["plan_date"] = r.get("plan_date")
        d["anchor_id"] = str(r["anchor_id"]) if r.get("anchor_id") else None
    return d
