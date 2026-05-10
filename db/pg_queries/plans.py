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
            "motif": master["motif"],
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


async def get_plans_for_range(
    conn: asyncpg.Connection,
    start_date: str,
    end_date: str,
) -> dict[str, dict]:
    """Return all plans and their tasks for the given inclusive date range.

    Issues ~6 queries total regardless of range length, replacing the previous
    O(days) loop over get_plan(). Dates with no plan entry are included with an
    empty-tasks structure matching the get_plan() shape.
    """
    # 1. Which dates in range have a plan row?
    plan_rows = await conn.fetch(
        "SELECT date FROM plans WHERE date BETWEEN $1 AND $2",
        start_date, end_date,
    )
    plan_dates = {str(r["date"]) for r in plan_rows}

    # 2. All tasks for dates in range.
    task_rows = await conn.fetch(
        """
        SELECT uuid, anchor_id, text, status, notes, position,
               followup_config, description, context_subject, context_node_id, motif, version,
               plan_date
        FROM tasks
        WHERE plan_date BETWEEN $1 AND $2
        ORDER BY plan_date, anchor_id, position
        """,
        start_date, end_date,
    )

    # Group tasks into {date: {anchor_id: {tasks, notes}}}.
    date_anchors: dict[str, dict] = {}
    for row in task_rows:
        d = str(row["plan_date"])
        aid = str(row["anchor_id"]) if row["anchor_id"] else None
        date_anchors.setdefault(d, {}).setdefault(aid, {"tasks": [], "notes": row["notes"]})
        date_anchors[d][aid]["tasks"].append(_row_to_task(row))

    # 3. Anchor-recurring masters — fetch once, expand per date in Python.
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

    # Fetch exception rows for all masters × all dates in range in one shot.
    master_uuids = [str(r["uuid"]) for r in master_rows]
    exception_set: set[tuple[str, str]] = set()
    if master_uuids:
        exc_rows = await conn.fetch(
            """
            SELECT recurrence_id, plan_date FROM tasks
            WHERE recurrence_id = ANY($1) AND plan_date BETWEEN $2 AND $3
            """,
            master_uuids, start_date, end_date,
        )
        exception_set = {(str(r["recurrence_id"]), str(r["plan_date"])) for r in exc_rows}

    # Determine all dates in range.
    dates_in_range: list[str] = []
    start_d = _dt.date.fromisoformat(start_date)
    end_d = _dt.date.fromisoformat(end_date)
    d = start_d
    while d <= end_d:
        dates_in_range.append(str(d))
        d += _dt.timedelta(days=1)

    # Expand masters for each date.
    for master in master_rows:
        rrule_str = master["rrule"]
        exdates = list(master["exdates"] or [])
        master_uuid = str(master["uuid"])
        for date_str in dates_in_range:
            if date_str not in plan_dates:
                continue
            if date_str in exdates:
                continue
            if (master_uuid, date_str) in exception_set:
                continue
            if not _anchor_recurring_occurs_on(rrule_str, date_str):
                continue
            aid = str(master["anchor_id"])
            date_anchors.setdefault(date_str, {}).setdefault(
                aid, {"tasks": [], "notes": master["notes"]}
            )
            date_anchors[date_str][aid]["tasks"].append({
                "id": master_uuid,
                "text": master["text"],
                "status": master["status"] or "pending",
                "position": master["position"] or 0,
                "description": master["description"],
                "context_subject": master["context_subject"],
                "context_node_id": str(master["context_node_id"]) if master["context_node_id"] else None,
                "followup_config": master["followup_config"],
                "motif": master["motif"],
                "version": master["version"] or 0,
                "anchor_id": aid,
                "plan_date": date_str,
                "rrule": rrule_str,
                "color": master["color"],
                "is_recurring_master": True,
                "blocks": [],
                "blocked_by": [],
            })

    # 4. Dependencies — one batch query for all task UUIDs in range.
    all_uuids = [
        t["id"]
        for anchors in date_anchors.values()
        for a in anchors.values()
        for t in a["tasks"]
        if t.get("id")
    ]
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
        for anchors in date_anchors.values():
            for anchor_data in anchors.values():
                for task in anchor_data["tasks"]:
                    task["blocked_by"] = blocked_by_map.get(task["id"], [])
                    task["blocks"] = blocks_map.get(task["id"], [])

    # 5. Acknowledgements and check-ins — two queries for the whole range.
    ack_rows = await conn.fetch(
        "SELECT anchor_id, acknowledged_at, plan_date FROM acknowledgements WHERE plan_date BETWEEN $1 AND $2",
        start_date, end_date,
    )
    date_acks: dict[str, dict] = {}
    for r in ack_rows:
        d_str = str(r["plan_date"])
        date_acks.setdefault(d_str, {})[str(r["anchor_id"])] = r["acknowledged_at"]

    checkin_rows = await conn.fetch(
        "SELECT * FROM check_ins WHERE plan_date BETWEEN $1 AND $2 ORDER BY plan_date, timestamp",
        start_date, end_date,
    )
    date_checkins: dict[str, list] = {}
    for r in checkin_rows:
        d_str = str(r["plan_date"])
        date_checkins.setdefault(d_str, []).append(dict(r))

    # 6. Assemble result for every date in range.
    result: dict[str, dict] = {}
    for date_str in dates_in_range:
        if date_str not in plan_dates:
            result[date_str] = {
                "date": date_str,
                "anchors": {},
                "acknowledgements": {},
                "check_in_log": [],
            }
        else:
            result[date_str] = {
                "date": date_str,
                "anchors": date_anchors.get(date_str, {}),
                "acknowledgements": date_acks.get(date_str, {}),
                "check_in_log": date_checkins.get(date_str, []),
            }
    return result


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
        "motif": r["motif"],
        "version": r.get("version", 0),
        "blocks": [],
        "blocked_by": [],
    }
    if include_schedule:
        d["plan_date"] = r.get("plan_date")
        d["anchor_id"] = str(r["anchor_id"]) if r.get("anchor_id") else None
    return d
