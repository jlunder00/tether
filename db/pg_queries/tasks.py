"""Async Postgres queries — tasks, subtasks, and dependencies."""
from __future__ import annotations
import uuid as _uuid
from typing import TYPE_CHECKING

import asyncpg

from db.pg_queries.errors import StaleReadError
from db.pg_queries.plans import _row_to_task

if TYPE_CHECKING:
    from integrations.models import TaskDraft


async def upsert_tasks(
    conn: asyncpg.Connection,
    date: str,
    anchor_id: str,
    tasks: list[dict],
    notes: str = "",
) -> list[dict]:
    """Add or update tasks for (date, anchor_id). Never deletes implicitly.

    Each task: {id?, text?, status?, followup_config?}.
    - With id: update that task (preserves text/status if not provided).
    - Without id but with text: create new task with fresh UUID.
    """
    task_dicts = [
        {"text": t, "status": "pending"} if isinstance(t, str) else t
        for t in tasks
    ]
    uid = current_setting = None
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )

    await conn.execute(
        """
        INSERT INTO plans (date, user_id)
        VALUES ($1, $2)
        ON CONFLICT (date, user_id) DO NOTHING
        """,
        date, user_uuid,
    )

    existing_rows = await conn.fetch(
        """
        SELECT uuid, text, status, followup_config
        FROM tasks
        WHERE plan_date = $1 AND anchor_id = $2 AND uuid IS NOT NULL
        """,
        date, _uuid.UUID(anchor_id),
    )
    existing_by_uuid = {str(r["uuid"]): dict(r) for r in existing_rows}

    for task in task_dicts:
        tid = task.get("id") or ""
        text = task.get("text")
        status = task.get("status")
        fc = task.get("followup_config")

        if tid:
            existing = existing_by_uuid.get(tid)
            if not existing:
                row = await conn.fetchrow(
                    "SELECT text, status FROM tasks WHERE uuid = $1", _uuid.UUID(tid)
                )
                if not row:
                    raise ValueError(f"Task UUID {tid} not found")
                existing = dict(row)
            text = text or existing["text"]
            status = status or existing.get("status") or "pending"
            await conn.execute(
                """
                UPDATE tasks
                SET plan_date = $1, anchor_id = $2, text = $3,
                    status = $4, followup_config = $5, notes = $6,
                    version = version + 1
                WHERE uuid = $7
                """,
                date, _uuid.UUID(anchor_id), text, status, fc, notes, _uuid.UUID(tid),
            )
        else:
            if not text:
                raise ValueError("New tasks must have 'text'")
            new_uuid = _uuid.uuid4()
            status = status or "pending"
            context_subject = task.get("context_subject")
            await conn.execute(
                "SELECT date FROM plans WHERE date = $1 AND user_id = $2 FOR UPDATE",
                date, user_uuid,
            )
            max_pos = await conn.fetchval(
                "SELECT COALESCE(MAX(position), -1) FROM tasks WHERE plan_date = $1 AND anchor_id = $2",
                date, _uuid.UUID(anchor_id),
            )
            await conn.execute(
                """
                INSERT INTO tasks
                    (uuid, user_id, plan_date, anchor_id, position, text,
                     status, followup_config, notes, context_subject)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                new_uuid, user_uuid, date, _uuid.UUID(anchor_id),
                max_pos + 1, text, status, fc, notes, context_subject,
            )

    all_rows = await conn.fetch(
        """
        SELECT uuid, text, status, position, followup_config,
               description, context_subject, context_node_id, version
        FROM tasks
        WHERE plan_date = $1 AND anchor_id = $2
        ORDER BY position
        """,
        date, _uuid.UUID(anchor_id),
    )
    return [_row_to_task(r) for r in all_rows]


async def patch_task_fields(
    conn: asyncpg.Connection,
    task_uuid: str,
    fields: dict,
    expected_version: int | None = None,
) -> dict | None:
    # Build SET clause from static column-name literals only — no user-supplied
    # string ever flows into the SQL text, satisfying static-analysis tools.
    # Each column name is a hard-coded string literal; only values are params.
    params: list = []
    set_parts: list[str] = []

    if "text" in fields:
        params.append(fields["text"])
        set_parts.append(f"text = ${len(params)}")
    if "status" in fields:
        params.append(fields["status"])
        set_parts.append(f"status = ${len(params)}")
    if "position" in fields:
        params.append(fields["position"])
        set_parts.append(f"position = ${len(params)}")
    if "followup_config" in fields:
        params.append(fields["followup_config"])
        set_parts.append(f"followup_config = ${len(params)}")
    if "description" in fields:
        params.append(fields["description"])
        set_parts.append(f"description = ${len(params)}")
    if "context_subject" in fields:
        params.append(fields["context_subject"])
        set_parts.append(f"context_subject = ${len(params)}")
    if "plan_date" in fields:
        params.append(fields["plan_date"])
        set_parts.append(f"plan_date = ${len(params)}")
    if "anchor_id" in fields:
        val = fields["anchor_id"]
        params.append(_uuid.UUID(val) if val is not None else None)
        set_parts.append(f"anchor_id = ${len(params)}")
    if "start_time" in fields:
        val = fields["start_time"]
        params.append(_parse_ts(val) if val is not None else None)
        set_parts.append(f"start_time = ${len(params)}")
    if "end_time" in fields:
        val = fields["end_time"]
        params.append(_parse_ts(val) if val is not None else None)
        set_parts.append(f"end_time = ${len(params)}")

    if not set_parts:
        return None

    set_parts.append("version = version + 1")

    if expected_version is not None:
        params.append(expected_version)
        where = f"uuid = ${len(params) + 1} AND version = ${len(params)}"
    else:
        where = f"uuid = ${len(params) + 1}"

    params.append(_uuid.UUID(task_uuid))

    result = await conn.execute(
        f"UPDATE tasks SET {', '.join(set_parts)} WHERE {where}",
        *params,
    )
    # result is like "UPDATE 1" or "UPDATE 0"
    if result == "UPDATE 0" and expected_version is not None:
        current = await conn.fetchval(
            "SELECT version FROM tasks WHERE uuid = $1", _uuid.UUID(task_uuid)
        )
        if current is None:
            return None
        raise StaleReadError(current)

    row = await conn.fetchrow(
        """
        SELECT uuid, text, status, position, followup_config,
               description, context_subject, context_node_id, version
        FROM tasks WHERE uuid = $1
        """,
        _uuid.UUID(task_uuid),
    )
    result = _row_to_task(row) if row else None

    if result is not None and "status" in fields:
        dep_rows = await conn.fetch(
            "SELECT blocked_id FROM dependencies WHERE blocker_type='task' AND blocker_id=$1 AND blocked_type='task'",
            task_uuid,
        )
        for dep_row in dep_rows:
            await resolve_blocked_status(conn, str(dep_row["blocked_id"]))
        await resolve_blocked_status(conn, task_uuid)
        # Re-read to reflect resolver's final state
        row = await conn.fetchrow(
            """
            SELECT uuid, text, status, position, followup_config,
                   description, context_subject, context_node_id, version
            FROM tasks WHERE uuid = $1
            """,
            _uuid.UUID(task_uuid),
        )
        if row:
            result = _row_to_task(row)
    return result


async def get_task_by_uuid(conn: asyncpg.Connection, task_uuid: str) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT uuid, plan_date, anchor_id, text, status, position,
               followup_config, description, context_subject, context_node_id, version
        FROM tasks WHERE uuid = $1
        """,
        _uuid.UUID(task_uuid),
    )
    return _row_to_task(row, include_schedule=True) if row else None


async def get_all_tasks(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT uuid, plan_date, anchor_id, text, status, position,
               followup_config, description, context_subject, context_node_id, version
        FROM tasks
        ORDER BY plan_date DESC NULLS LAST, anchor_id, position
        """
    )
    return [_row_to_task(r, include_schedule=True) for r in rows]


async def create_unscheduled_task(
    conn: asyncpg.Connection,
    text: str,
    description: str | None = None,
    status: str = "pending",
    context_subject: str | None = None,
) -> dict:
    """Create a task with no plan_date or anchor_id (backlog task)."""
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    new_uuid = _uuid.uuid4()
    row = await conn.fetchrow(
        """
        INSERT INTO tasks (uuid, user_id, text, status, description, context_subject)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING uuid, text, status, position, followup_config, description, context_subject, context_node_id, version
        """,
        new_uuid, user_uuid, text, status, description, context_subject,
    )
    new_task = _row_to_task(row)
    await resolve_blocked_status(conn, new_task["id"])
    return new_task


async def get_unscheduled_tasks(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT uuid, text, status, position, followup_config,
               description, context_subject, context_node_id, version
        FROM tasks WHERE plan_date IS NULL
        ORDER BY position
        """
    )
    return [_row_to_task(r) for r in rows]


async def delete_task_by_uuid(conn: asyncpg.Connection, task_uuid: str) -> None:
    downstream_rows = await conn.fetch(
        "SELECT blocked_id FROM dependencies WHERE blocker_type='task' AND blocker_id=$1 AND blocked_type='task'",
        task_uuid,
    )
    downstream = [str(r["blocked_id"]) for r in downstream_rows]

    uid = _uuid.UUID(task_uuid)
    await conn.execute("DELETE FROM subtasks WHERE task_id = $1", task_uuid)
    await conn.execute(
        "DELETE FROM links WHERE parent_type = 'tasks' AND parent_id = $1", task_uuid
    )
    await conn.execute(
        "DELETE FROM dependencies WHERE (blocker_type='task' AND blocker_id=$1) OR (blocked_type='task' AND blocked_id=$1)",
        task_uuid,
    )
    await conn.execute("DELETE FROM milestone_tasks WHERE task_id = $1", task_uuid)
    await conn.execute("DELETE FROM followup_state WHERE task_id = $1", task_uuid)
    await conn.execute("DELETE FROM tasks WHERE uuid = $1", uid)

    for dep_uuid in downstream:
        await resolve_blocked_status(conn, dep_uuid)


async def move_task_atomic(
    conn: asyncpg.Connection,
    task_uuid: str,
    date: str | None,
    anchor_id: str | None,
    position: int | None = None,
) -> None:
    uid = _uuid.UUID(task_uuid)
    row = await conn.fetchrow("SELECT plan_date FROM tasks WHERE uuid = $1", uid)
    if not row:
        raise ValueError(f"Task {task_uuid} not found")
    if date is None or anchor_id is None:
        await conn.execute(
            "UPDATE tasks SET plan_date = NULL, anchor_id = NULL, position = 0, version = version + 1 WHERE uuid = $1",
            uid,
        )
        return
    aid = _uuid.UUID(anchor_id)
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    await conn.execute(
        "INSERT INTO plans (date, user_id) VALUES ($1, $2) ON CONFLICT (date, user_id) DO NOTHING",
        date, user_uuid,
    )
    if position is None:
        await conn.execute(
            "SELECT date FROM plans WHERE date = $1 AND user_id = $2 FOR UPDATE",
            date, user_uuid,
        )
        position = (await conn.fetchval(
            "SELECT COALESCE(MAX(position), -1) FROM tasks WHERE plan_date = $1 AND anchor_id = $2",
            date, aid,
        )) + 1
    await conn.execute(
        "UPDATE tasks SET plan_date = $1, anchor_id = $2, position = $3, version = version + 1 WHERE uuid = $4",
        date, aid, position, uid,
    )


async def search_tasks(conn: asyncpg.Connection, q: str) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT uuid, text, status, plan_date, anchor_id, context_subject, version
        FROM tasks
        WHERE text ILIKE '%' || $1 || '%'
        ORDER BY plan_date DESC NULLS LAST, text
        LIMIT 50
        """,
        q,
    )
    return [_row_to_task(r, include_schedule=True) for r in rows]


async def search_entities(
    conn: asyncpg.Connection, query: str, entity_type: str = "all"
) -> list[dict]:
    """Search tasks and/or milestones by text. Returns [{id, label, sublabel, type}]."""
    results = []
    if entity_type in ("all", "task"):
        rows = await conn.fetch(
            """
            SELECT uuid, text, anchor_id, plan_date FROM tasks
            WHERE text ILIKE '%' || $1 || '%'
            ORDER BY plan_date DESC NULLS LAST LIMIT 20
            """,
            query,
        )
        for r in rows:
            results.append({
                "id": str(r["uuid"]),
                "label": r["text"],
                "sublabel": f"task · {r['anchor_id']} · {r['plan_date']}",
                "type": "task",
            })
    if entity_type in ("all", "milestone"):
        rows = await conn.fetch(
            """
            SELECT id, name, context_subject FROM milestones
            WHERE name ILIKE '%' || $1 || '%'
            ORDER BY name LIMIT 20
            """,
            query,
        )
        for r in rows:
            results.append({
                "id": str(r["id"]),
                "label": r["name"],
                "sublabel": f"milestone · {r['context_subject']}",
                "type": "milestone",
            })
    return results


# ── Dependencies ──────────────────────────────────────────────────────────────

async def add_dependency(
    conn: asyncpg.Connection,
    blocker_type: str, blocker_id: str,
    blocked_type: str, blocked_id: str,
) -> int:
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    row = await conn.fetchrow(
        """
        INSERT INTO dependencies (user_id, blocker_type, blocker_id, blocked_type, blocked_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (user_id, blocker_type, blocker_id, blocked_type, blocked_id) DO NOTHING
        RETURNING id
        """,
        user_uuid, blocker_type, blocker_id, blocked_type, blocked_id,
    )
    if row:
        dep_id = row["id"]
    else:
        row = await conn.fetchrow(
            "SELECT id FROM dependencies WHERE blocker_type=$1 AND blocker_id=$2 AND blocked_type=$3 AND blocked_id=$4",
            blocker_type, blocker_id, blocked_type, blocked_id,
        )
        dep_id = row["id"]
    if blocked_type == "task":
        await resolve_blocked_status(conn, blocked_id)
    return dep_id


async def resolve_blocked_status(
    conn: asyncpg.Connection,
    task_uuid: str,
    _visited: set[str] | None = None,
) -> None:
    """Auto-flip task status between 'pending' and 'blocked' based on open blockers.

    Only transitions pending↔blocked. Never touches done/skipped.
    _visited prevents infinite loops in cyclic dependency graphs.
    """
    if _visited is None:
        _visited = set()
    if task_uuid in _visited:
        return
    _visited.add(task_uuid)

    row = await conn.fetchrow("SELECT status FROM tasks WHERE uuid = $1", _uuid.UUID(task_uuid))
    if row is None:
        return
    current = row["status"]
    if current in ("done", "skipped"):
        return

    blocker_rows = await conn.fetch(
        """
        SELECT t.status FROM dependencies d
        JOIN tasks t ON t.uuid::text = d.blocker_id
        WHERE d.blocked_type = 'task' AND d.blocked_id = $1
          AND d.blocker_type = 'task'
        """,
        task_uuid,
    )
    has_open = any(r["status"] not in ("done", "skipped") for r in blocker_rows)

    new_status: str | None = None
    if has_open and current != "blocked":
        new_status = "blocked"
    elif not has_open and current == "blocked":
        new_status = "pending"

    if new_status is None:
        return

    await conn.execute("UPDATE tasks SET status = $1 WHERE uuid = $2", new_status, _uuid.UUID(task_uuid))

    dependents_to_cascade = await conn.fetch(
        """
        SELECT d.blocked_id FROM dependencies d
        WHERE d.blocker_type = 'task' AND d.blocker_id = $1
          AND d.blocked_type = 'task'
        """,
        task_uuid,
    )
    cascade_uuids = [str(r["blocked_id"]) for r in dependents_to_cascade]

    for dep_uuid in cascade_uuids:
        await resolve_blocked_status(conn, dep_uuid, _visited)


async def remove_dependency(conn: asyncpg.Connection, dep_id: int) -> None:
    row = await conn.fetchrow(
        "SELECT blocked_type, blocked_id FROM dependencies WHERE id = $1", dep_id
    )
    await conn.execute("DELETE FROM dependencies WHERE id = $1", dep_id)
    if row and row["blocked_type"] == "task":
        await resolve_blocked_status(conn, str(row["blocked_id"]))


async def get_dependencies_for(
    conn: asyncpg.Connection, entity_type: str, entity_id: str
) -> dict:
    async def _resolve_name(etype, eid):
        if etype == "task":
            return await conn.fetchval("SELECT text FROM tasks WHERE uuid = $1", _uuid.UUID(eid))
        elif etype == "milestone":
            name = await conn.fetchval("SELECT name FROM context_nodes WHERE id = $1", _uuid.UUID(eid))
            if not name:
                name = await conn.fetchval("SELECT name FROM milestones WHERE id = $1", _uuid.UUID(eid))
            return name
        return None

    blocker_rows = await conn.fetch(
        "SELECT id, blocked_type, blocked_id FROM dependencies WHERE blocker_type=$1 AND blocker_id=$2",
        entity_type, entity_id,
    )
    blocked_rows = await conn.fetch(
        "SELECT id, blocker_type, blocker_id FROM dependencies WHERE blocked_type=$1 AND blocked_id=$2",
        entity_type, entity_id,
    )
    blocks = [
        {"id": r["id"], "type": r["blocked_type"], "entity_id": r["blocked_id"],
         "name": await _resolve_name(r["blocked_type"], r["blocked_id"])}
        for r in blocker_rows
    ]
    blocked_by = [
        {"id": r["id"], "type": r["blocker_type"], "entity_id": r["blocker_id"],
         "name": await _resolve_name(r["blocker_type"], r["blocker_id"])}
        for r in blocked_rows
    ]
    return {"blocks": blocks, "blocked_by": blocked_by}


async def get_full_task_dependencies(conn: asyncpg.Connection, task_uuid: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT task_id, blocked_by_id FROM task_dependencies WHERE task_id = $1",
        _uuid.UUID(task_uuid),
    )
    return [{"task_id": str(r["task_id"]), "blocked_by_id": str(r["blocked_by_id"])} for r in rows]


async def add_task_dependency(conn: asyncpg.Connection, task_id: str, blocked_by_id: str) -> None:
    await conn.execute(
        "INSERT INTO task_dependencies (task_id, blocked_by_id, user_id) "
        "VALUES ($1, $2, current_setting('app.current_user_id', true)::uuid) "
        "ON CONFLICT DO NOTHING",
        _uuid.UUID(task_id), _uuid.UUID(blocked_by_id),
    )


async def remove_task_dependency(conn: asyncpg.Connection, task_id: str, blocked_by_id: str) -> None:
    await conn.execute(
        "DELETE FROM task_dependencies WHERE task_id = $1 AND blocked_by_id = $2",
        _uuid.UUID(task_id), _uuid.UUID(blocked_by_id),
    )


# ── Subtasks ──────────────────────────────────────────────────────────────────

async def get_subtasks(conn: asyncpg.Connection, task_id: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT id, task_id, text, done, position FROM subtasks WHERE task_id = $1 ORDER BY position",
        task_id,
    )
    return [dict(r) for r in rows]


async def create_subtask(conn: asyncpg.Connection, task_id: str, text: str, position: int) -> dict:
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    row = await conn.fetchrow(
        "INSERT INTO subtasks (user_id, task_id, text, done, position) VALUES ($1, $2, $3, FALSE, $4) RETURNING id, task_id, text, done, position",
        user_uuid, task_id, text, position,
    )
    return dict(row)


async def update_subtask(conn: asyncpg.Connection, subtask_id: int, **fields) -> None:
    # Build SET clause from static column-name literals only.
    params: list = []
    set_parts: list[str] = []

    if "text" in fields:
        params.append(fields["text"])
        set_parts.append(f"text = ${len(params)}")
    if "done" in fields:
        params.append(bool(fields["done"]))
        set_parts.append(f"done = ${len(params)}")
    if "position" in fields:
        params.append(fields["position"])
        set_parts.append(f"position = ${len(params)}")

    if not set_parts:
        return

    params.append(subtask_id)
    await conn.execute(
        f"UPDATE subtasks SET {', '.join(set_parts)} WHERE id = ${len(params)}", *params
    )


async def delete_subtask(conn: asyncpg.Connection, subtask_id: int) -> None:
    await conn.execute("DELETE FROM subtasks WHERE id = $1", subtask_id)


async def reorder_subtasks(conn: asyncpg.Connection, task_id: str, id_order: list[int]) -> None:
    for pos, subtask_id in enumerate(id_order):
        await conn.execute(
            "UPDATE subtasks SET position = $1 WHERE id = $2 AND task_id = $3",
            pos, subtask_id, task_id,
        )


async def upsert_task_from_draft(
    conn: asyncpg.Connection,
    user_id: str,
    draft: "TaskDraft",
) -> dict:
    """Upsert an external-sourced task from a TaskDraft.

    Conflict key: (user_id, source, external_id) — the partial unique index
    on tasks WHERE source IS NOT NULL.

    On conflict: updates presentation fields (title, times, description,
    external_url, source_status) and bumps version.
    Does NOT overwrite user-owned fields (plan_date, anchor_id, position,
    status, notes) on conflict — those belong to the user.

    On insert: task lands as unscheduled (plan_date=NULL, anchor_id=NULL,
    position=0, status='pending').
    """
    new_uuid = _uuid.uuid4()
    row = await conn.fetchrow(
        """
        INSERT INTO tasks
            (uuid, user_id, text, source, external_id,
             start_time, end_time, description, external_url, source_status,
             rrule, recurrence_id, exdates, original_start_time,
             status, position)
        VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, 'pending', 0)
        ON CONFLICT (user_id, source, external_id) WHERE source IS NOT NULL
        DO UPDATE SET
            text               = EXCLUDED.text,
            start_time         = EXCLUDED.start_time,
            end_time           = EXCLUDED.end_time,
            description        = EXCLUDED.description,
            external_url       = EXCLUDED.external_url,
            source_status      = EXCLUDED.source_status,
            rrule              = EXCLUDED.rrule,
            recurrence_id      = EXCLUDED.recurrence_id,
            exdates            = EXCLUDED.exdates,
            original_start_time = EXCLUDED.original_start_time,
            version            = tasks.version + 1
        RETURNING
            uuid, text, status, position, followup_config,
            description, context_subject, context_node_id, version
        """,
        new_uuid,
        user_id,
        draft.title,
        draft.source,
        draft.external_id,
        draft.start_time,
        draft.end_time,
        draft.description,
        draft.external_url,
        draft.source_status,
        draft.rrule,
        draft.recurrence_id,
        draft.exdates or [],
        draft.original_start_time,
    )
    return _row_to_task(row)


# ─── Event queries (tasks with start_time/end_time set) ───────────────────────

from datetime import datetime as _datetime, timedelta as _timedelta


def _parse_ts(s: str) -> _datetime:
    """Parse an ISO 8601 timestamp string to an aware datetime for asyncpg.

    asyncpg requires datetime objects for TIMESTAMPTZ parameters — it does not
    coerce strings even when the SQL uses a ::timestamptz cast. Python 3.10's
    fromisoformat() also rejects the 'Z' suffix, so we normalise it first.
    """
    return _datetime.fromisoformat(s.replace("Z", "+00:00"))


def _row_to_event(row, *, is_recurring: bool = False, is_occurrence: bool = False) -> dict:
    """Map a task row that has event fields to CalendarEvent shape."""
    r = dict(row)
    st = r.get("start_time")
    et = r.get("end_time")
    uid = str(r["uuid"]) if r.get("uuid") else None
    return {
        "id": uid,
        "title": r.get("text", ""),
        "start_time": st.isoformat() if st else None,
        "end_time": et.isoformat() if et else None,
        "source": r.get("source") or "tether",
        "external_id": r.get("external_id"),
        "task_id": uid,
        "anchor_id": str(r["anchor_id"]) if r.get("anchor_id") else None,
        "color": None,
        "context_subject": r.get("context_subject"),
        "is_recurring": is_recurring,
        "is_occurrence": is_occurrence,
    }


def _parse_exdate_value(value: str) -> _datetime | None:
    """Parse a single EXDATE datetime token into a UTC-aware datetime.

    Handles iCalendar compact form without hyphens/colons, e.g. 20260511T090000Z,
    and all-day date tokens without a time component, e.g. 20260511 or 2026-05-11.
    Returns None (with a warning) if parsing fails.
    """
    import logging
    _logger = logging.getLogger(__name__)
    try:
        value = value.strip().replace("Z", "+00:00")
        if "T" in value:
            if len(value) >= 15 and "-" not in value[:8]:
                # Insert separators: YYYYMMDDTHHMMSS → YYYY-MM-DDTHH:MM:SS
                value = (
                    f"{value[:4]}-{value[4:6]}-{value[6:8]}"
                    f"T{value[9:11]}:{value[11:13]}:{value[13:15]}{value[15:]}"
                )
        else:
            # All-day date token (VALUE=DATE format): "20260511" or "2026-05-11"
            from datetime import date as _date, timezone as _tz
            bare = value.replace("+00:00", "").strip()
            if len(bare) == 8 and "-" not in bare:
                bare = f"{bare[:4]}-{bare[4:6]}-{bare[6:8]}"
            d = _date.fromisoformat(bare)
            return _datetime(d.year, d.month, d.day, tzinfo=_tz.utc)
        dt = _datetime.fromisoformat(value)
        if dt.tzinfo is None:
            from datetime import timezone as _tz
            dt = dt.replace(tzinfo=_tz.utc)
        return dt
    except ValueError:
        _logger.warning("EXDATE token could not be parsed, occurrence will NOT be suppressed: %r", value)
        return None


def _parse_exdate(exdate_line: str) -> list[_datetime]:
    """Extract datetimes from an EXDATE line.

    Handles single and comma-separated RFC 5545 formats:
      EXDATE;TZID=UTC:20260511T090000Z
      EXDATE;TZID=UTC:20260511T090000Z,20260518T090000Z

    Returns a list of UTC-aware datetimes (may be empty on parse failure).
    """
    try:
        # Value portion is everything after the last colon
        value_part = exdate_line.rsplit(":", 1)[-1].strip()
        return [
            dt for raw in value_part.split(",")
            if (dt := _parse_exdate_value(raw)) is not None
        ]
    except Exception:
        return []


def expand_recurring(task: dict, window_start: _datetime, window_end: _datetime) -> list[dict]:
    """Expand a recurring task's RRULE into concrete occurrences within the window.

    Args:
        task: CalendarEvent-shaped dict with rrule, start_time, end_time, exdates.
        window_start: inclusive start of the query window (tz-aware).
        window_end: inclusive end of the query window (tz-aware).

    Returns:
        List of CalendarEvent dicts, one per occurrence, with is_occurrence=True.
        Occurrences matching any exdate are excluded.
    """
    from dateutil.rrule import rrulestr

    rrule_str = task.get("rrule")
    if not rrule_str:
        return []

    raw_start = task.get("start_time")
    raw_end = task.get("end_time")
    if not raw_start:
        return []

    dtstart = _parse_ts(raw_start) if isinstance(raw_start, str) else raw_start
    if raw_end:
        dtend = _parse_ts(raw_end) if isinstance(raw_end, str) else raw_end
        duration = dtend - dtstart
    else:
        duration = _timedelta(hours=1)

    # Build excluded dates set — date-only comparison (year, month, day).
    # NOTE: This correctly suppresses one occurrence per day for daily/weekly series.
    # Known limitation: sub-daily recurrences (FREQ=HOURLY etc.) with multiple occurrences
    # on the same calendar date will have ALL same-day occurrences suppressed by a single
    # EXDATE. Tether doesn't currently produce hourly series, so this is acceptable.
    # Track separately if sub-daily support is added.
    exdate_dates: set[tuple[int, int, int]] = set()
    for exdate_line in (task.get("exdates") or []):
        for dt in _parse_exdate(exdate_line):
            exdate_dates.add((dt.year, dt.month, dt.day))

    rule = rrulestr(rrule_str, dtstart=dtstart, ignoretz=False)

    # Normalize window bounds to match dtstart's tz-awareness so rule.between()
    # never raises "can't compare offset-naive and offset-aware datetimes".
    #
    # Typical case: dtstart is tz-aware (asyncpg TIMESTAMPTZ) but window bounds
    # are naive (API query params sent without timezone offset → _parse_ts returns
    # naive). Treat naive bounds as UTC.
    #
    # Symmetric guard: if dtstart is naive (unexpected, but possible if the column
    # ever returns TIMESTAMP instead of TIMESTAMPTZ), strip tz from aware bounds.
    from datetime import timezone as _tz
    if dtstart.tzinfo is not None:
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=_tz.utc)
        if window_end.tzinfo is None:
            window_end = window_end.replace(tzinfo=_tz.utc)
    else:
        if window_start.tzinfo is not None:
            window_start = window_start.replace(tzinfo=None)
        if window_end.tzinfo is not None:
            window_end = window_end.replace(tzinfo=None)

    occurrences = []
    for dt in rule.between(window_start, window_end, inc=True):
        if (dt.year, dt.month, dt.day) in exdate_dates:
            continue
        occ = {
            **task,
            "start_time": dt.isoformat(),
            "end_time": (dt + duration).isoformat(),
            "is_occurrence": True,
            "is_recurring": True,
        }
        occurrences.append(occ)
    return occurrences


def _rrule_set_until(rrule_str: str, until_dt: _datetime) -> str:
    """Return a new RRULE string with UNTIL set to *until_dt* (UTC, second precision).

    Removes any existing UNTIL or COUNT clause before appending the new UNTIL.
    *until_dt* is formatted as iCal compact UTC: YYYYMMDDTHHMMSSZ.
    """
    import re
    until_str = until_dt.strftime("%Y%m%dT%H%M%SZ")
    # Strip RRULE: prefix if present, work on the property value only
    prefix = ""
    value = rrule_str
    if rrule_str.upper().startswith("RRULE:"):
        prefix = rrule_str[:6]
        value = rrule_str[6:]
    # Remove existing UNTIL= and COUNT= clauses (case-insensitive)
    value = re.sub(r";?UNTIL=[^;]*", "", value, flags=re.IGNORECASE)
    value = re.sub(r";?COUNT=[^;]*", "", value, flags=re.IGNORECASE)
    # Build the new value then strip stray leading/trailing semicolons.
    # Prevents "RRULE:;UNTIL=..." when value is empty.
    value = (value + ";UNTIL=" + until_str).strip(";")
    return f"{prefix}{value}"


def assign_event_anchor(
    event: dict,
    anchors: list[dict],
    now_utc: "datetime",  # noqa: F821 — datetime imported at module level as _datetime
) -> str | None:
    """Return the anchor_id best matching an event for the dashboard now-view.

    All time comparison is done in server-local (naive) time so anchor HH:MM
    strings are directly comparable to event times.  now_utc is converted with
    ``astimezone()`` which reads the system timezone (Pi local == user local).

    Priority rules (evaluated in order):
      1. Currently-active anchor (whose window contains now) overlaps event → return it.
      2. No active-anchor overlap, but a future anchor will → return next upcoming.
      3. Active anchor has moved past event end → return last overlapping anchor.
      4. now is before all anchor windows → return first anchor.
      5. No anchors overlap at all → return first anchor (fallback).

    Returns None only when anchors is empty.
    """
    if not anchors:
        return None

    now_local = now_utc.astimezone().replace(tzinfo=None)
    today = now_local.date()

    def _anchor_window(a: dict) -> tuple["datetime", "datetime"]:  # noqa: F821
        h, m = map(int, a["time"].split(":"))
        start = _datetime(today.year, today.month, today.day, h, m)
        return start, start + _timedelta(minutes=a.get("duration_minutes", 0))

    def _event_times() -> tuple["datetime", "datetime"]:  # noqa: F821
        raw_start = event.get("start_time") or ""
        raw_end = event.get("end_time") or ""
        # Parse UTC ISO → local naive
        def _to_naive_local(s: str) -> "_datetime":  # noqa: F821
            dt = _parse_ts(s)
            return dt.astimezone().replace(tzinfo=None)
        return _to_naive_local(raw_start), _to_naive_local(raw_end)

    def _overlaps(a_start, a_end, e_start, e_end) -> bool:
        return a_start < e_end and a_end > e_start

    ev_start, ev_end = _event_times()

    # Rule 4: before all anchors
    first_window_start, _ = _anchor_window(anchors[0])
    if now_local < first_window_start:
        return anchors[0]["id"]

    # Classify each anchor
    active_anchor = None
    overlapping: list[dict] = []
    for a in anchors:
        a_start, a_end = _anchor_window(a)
        if a_start <= now_local < a_end:
            active_anchor = a
        if _overlaps(a_start, a_end, ev_start, ev_end):
            overlapping.append(a)

    # Rule 1: active anchor overlaps event
    if active_anchor and any(a["id"] == active_anchor["id"] for a in overlapping):
        return active_anchor["id"]

    # Rule 3: active anchor moved past event end — find last overlapping
    if active_anchor:
        past_overlapping = [
            a for a in overlapping
            if _anchor_window(a)[1] <= now_local
        ]
        if past_overlapping:
            return past_overlapping[-1]["id"]

    # Rule 2: future anchor will overlap event
    future_overlapping = [
        a for a in overlapping
        if _anchor_window(a)[0] > now_local
    ]
    if future_overlapping:
        return future_overlapping[0]["id"]

    # Rule 5: no anchors overlap at all — first anchor fallback
    return anchors[0]["id"]


async def promote_task_to_event(
    conn: asyncpg.Connection,
    task_uuid: str,
    start_time: str,
    end_time: str,
) -> dict | None:
    """Stamp an existing task with start/end time, making it a calendar event.

    Returns CalendarEvent-shaped dict, or None if the task doesn't exist.
    """
    row = await conn.fetchrow(
        """
        UPDATE tasks
        SET start_time = $1,
            end_time   = $2,
            source     = COALESCE(source, 'tether'),
            version    = version + 1
        WHERE uuid = $3
        RETURNING uuid, text, start_time, end_time, source, external_id, anchor_id, context_subject
        """,
        _parse_ts(start_time), _parse_ts(end_time), _uuid.UUID(task_uuid),
    )
    return _row_to_event(row) if row else None


async def get_events_for_range(
    conn: asyncpg.Connection,
    start: str,
    end: str,
) -> list[dict]:
    """Return all calendar events whose occurrence falls within [start, end].

    Handles two kinds of tasks:
    1. Single events (rrule IS NULL): start_time must fall in the window.
       Exception instances (recurrence_id IS NOT NULL) are treated as single
       events — they override a specific occurrence of a series.
    2. Recurring series masters (rrule IS NOT NULL): fetched separately and
       expanded via RRULE; occurrences outside the window are dropped.
       Exception instances from the same user are fetched and substitute
       the computed occurrence for their specific date.
    """
    window_start = _parse_ts(start)
    window_end = _parse_ts(end)

    # 1. Single events (non-recurring, non-exception): rrule IS NULL and no recurrence_id
    single_rows = await conn.fetch(
        """
        SELECT uuid, text, start_time, end_time, source, external_id, anchor_id,
               rrule, recurrence_id, exdates, original_start_time, context_subject
        FROM tasks
        WHERE start_time IS NOT NULL
          AND rrule IS NULL
          AND recurrence_id IS NULL
          AND start_time >= $1
          AND start_time <= $2
        ORDER BY start_time
        """,
        window_start, window_end,
    )
    results: list[dict] = [_row_to_event(r) for r in single_rows]

    # 2. Recurring series masters: expand via RRULE
    recurring_rows = await conn.fetch(
        """
        SELECT uuid, text, start_time, end_time, source, external_id, anchor_id,
               rrule, recurrence_id, exdates, original_start_time, context_subject
        FROM tasks
        WHERE rrule IS NOT NULL
          AND start_time IS NOT NULL
        ORDER BY start_time
        """,
    )

    if not recurring_rows:
        return sorted(results, key=lambda e: e["start_time"] or "")

    # Fetch all exception instances (recurrence_id IS NOT NULL) for series in window.
    # No time filter here — moved exceptions may fall outside the query window in
    # start_time but still need to suppress the computed occurrence.
    master_external_ids = [str(r["external_id"]) for r in recurring_rows if r["external_id"]]
    exception_rows: list = []
    if master_external_ids:
        exception_rows = await conn.fetch(
            """
            SELECT uuid, text, start_time, end_time, source, external_id, anchor_id,
                   rrule, recurrence_id, exdates, original_start_time, context_subject
            FROM tasks
            WHERE recurrence_id = ANY($1::text[])
              AND (source_status IS NULL OR source_status != 'cancelled')
            """,
            master_external_ids,
        )

    # Key exceptions by (recurrence_id, original_date) for substitution.
    # original_start_time is the slot being replaced (what expand_recurring would compute).
    # start_time is where the exception actually appears (may differ for moved exceptions).
    exception_by_key: dict[tuple[str, tuple[int, int, int]], dict | None] = {}
    for exc_row in exception_rows:
        rid = exc_row["recurrence_id"]
        if not rid:
            continue
        # Use original_start_time to key the occurrence being replaced; fall back to start_time
        original_st = exc_row.get("original_start_time") or exc_row.get("start_time")
        if not original_st:
            continue
        if hasattr(original_st, "date"):
            key_date = (original_st.year, original_st.month, original_st.day)
        else:
            dt = _parse_ts(str(original_st))
            key_date = (dt.year, dt.month, dt.day)
        # Only include in results if the exception itself falls within the window
        exc_start = exc_row.get("start_time")
        if exc_start and window_start <= exc_start <= window_end:
            exc = _row_to_event(exc_row, is_occurrence=True, is_recurring=True)
            exception_by_key[(str(rid), key_date)] = exc
        else:
            # Moved outside window — still register the key to suppress the ghost occurrence
            exception_by_key[(str(rid), key_date)] = None

    # Expand each recurring master and substitute exception instances
    for master_row in recurring_rows:
        task = _row_to_event(master_row, is_recurring=True)
        task["rrule"] = master_row["rrule"]
        task["exdates"] = list(master_row["exdates"] or [])
        task["start_time"] = master_row["start_time"].isoformat() if master_row["start_time"] else None
        task["end_time"] = master_row["end_time"].isoformat() if master_row["end_time"] else None

        for occ in expand_recurring(task, window_start, window_end):
            occ_dt = _parse_ts(occ["start_time"])
            key = (str(master_row["external_id"] or ""), (occ_dt.year, occ_dt.month, occ_dt.day))
            if key in exception_by_key:
                # exception_by_key[key] is None when the moved exception falls outside the
                # query window — suppress the ghost occurrence but emit nothing.
                exc = exception_by_key[key]
                if exc is not None:
                    results.append(exc)
            else:
                results.append(occ)

    return sorted(results, key=lambda e: e["start_time"] or "")


async def delete_event(
    conn: asyncpg.Connection,
    event_uuid: str,
) -> bool:
    """Hard-delete a single event (or recurring master + its orphan exceptions).

    For a recurring master (rrule IS NOT NULL), also deletes all exception rows
    whose recurrence_id matches the master's external_id.

    Returns True if a row was deleted, False if not found.
    """
    async with conn.transaction():
        # Check if this is a recurring master with an external_id
        master = await conn.fetchrow(
            "SELECT external_id FROM tasks WHERE uuid = $1 AND start_time IS NOT NULL",
            _uuid.UUID(event_uuid),
        )
        if master is None:
            return False

        external_id = master["external_id"]
        if external_id:
            # Collect exception UUIDs so child-table cleanup can reference them by text ID.
            # task_id columns in subtasks/links/dependencies/milestone_tasks/followup_state
            # have no FK REFERENCES tasks(uuid) ON DELETE CASCADE — cleanup must be explicit.
            exc_uuids = await conn.fetch(
                "SELECT uuid FROM tasks WHERE recurrence_id = $1",
                str(external_id),
            )
            for row in exc_uuids:
                exc_id = str(row["uuid"])
                await conn.execute("DELETE FROM subtasks WHERE task_id = $1", exc_id)
                await conn.execute(
                    "DELETE FROM links WHERE parent_type = 'tasks' AND parent_id = $1", exc_id
                )
                await conn.execute(
                    "DELETE FROM dependencies WHERE (blocker_type='task' AND blocker_id=$1)"
                    " OR (blocked_type='task' AND blocked_id=$1)",
                    exc_id,
                )
                await conn.execute("DELETE FROM milestone_tasks WHERE task_id = $1", exc_id)
                await conn.execute("DELETE FROM followup_state WHERE task_id = $1", exc_id)

            await conn.execute(
                "DELETE FROM tasks WHERE recurrence_id = $1",
                str(external_id),
            )

        # Clean child tables for the master row before deleting it
        await conn.execute("DELETE FROM subtasks WHERE task_id = $1", event_uuid)
        await conn.execute(
            "DELETE FROM links WHERE parent_type = 'tasks' AND parent_id = $1", event_uuid
        )
        await conn.execute(
            "DELETE FROM dependencies WHERE (blocker_type='task' AND blocker_id=$1)"
            " OR (blocked_type='task' AND blocked_id=$1)",
            event_uuid,
        )
        await conn.execute("DELETE FROM milestone_tasks WHERE task_id = $1", event_uuid)
        await conn.execute("DELETE FROM followup_state WHERE task_id = $1", event_uuid)

        result = await conn.execute(
            "DELETE FROM tasks WHERE uuid = $1",
            _uuid.UUID(event_uuid),
        )
        return result == "DELETE 1"


async def delete_recurring_occurrence(
    conn: asyncpg.Connection,
    event_uuid: str,
    original_start_time: str,
) -> bool:
    """Suppress a single occurrence of a recurring event by appending an EXDATE.

    Mutates the master row's exdates array in place — does NOT delete any row.
    The date token written is ISO compact (e.g. "20260511") for iCalendar compatibility.

    Returns True if the master was found and updated, False if not found.
    """
    master = await conn.fetchrow(
        """
        SELECT uuid, rrule, exdates FROM tasks
        WHERE uuid = $1 AND start_time IS NOT NULL
        """,
        _uuid.UUID(event_uuid),
    )
    if master is None:
        return False
    if not master["rrule"]:
        raise ValueError(f"Task {event_uuid} is not a recurring event")

    dt = _parse_ts(original_start_time)
    # Write compact iCalendar EXDATE;VALUE=DATE token
    exdate_token = f"EXDATE;VALUE=DATE:{dt.year:04d}{dt.month:02d}{dt.day:02d}"
    existing = list(master["exdates"] or [])
    if exdate_token not in existing:
        existing.append(exdate_token)

    await conn.execute(
        "UPDATE tasks SET exdates = $1, version = version + 1 WHERE uuid = $2",
        existing, _uuid.UUID(event_uuid),
    )
    return True


async def delete_recurring_from(
    conn: asyncpg.Connection,
    event_uuid: str,
    original_start_time: str,
) -> bool:
    """Truncate a recurring series by setting UNTIL one instant before original_start_time.

    Mutates the master's rrule in place — does NOT create a new master.
    Also hard-deletes any exception rows that fall on or after original_start_time.

    Returns True if the master was found and updated, False if not found.
    """
    master = await conn.fetchrow(
        """
        SELECT uuid, rrule, external_id FROM tasks
        WHERE uuid = $1 AND start_time IS NOT NULL
        """,
        _uuid.UUID(event_uuid),
    )
    if master is None:
        return False
    if not master["rrule"]:
        raise ValueError(f"Task {event_uuid} is not a recurring event")

    cutoff = _parse_ts(original_start_time)
    # UNTIL is exclusive — set to one second before the first deleted occurrence
    until_dt = cutoff - _timedelta(seconds=1)

    new_rrule = _rrule_set_until(master["rrule"] or "", until_dt)

    async with conn.transaction():
        await conn.execute(
            "UPDATE tasks SET rrule = $1, version = version + 1 WHERE uuid = $2",
            new_rrule, _uuid.UUID(event_uuid),
        )

        # Remove exceptions on or after the cutoff date
        external_id = master["external_id"]
        if external_id:
            await conn.execute(
                """
                DELETE FROM tasks
                WHERE recurrence_id = $1
                  AND original_start_time >= $2
                """,
                str(external_id), cutoff,
            )

    return True


def _rewrite_dtstart_in_rrule(rrule_str: str, delta: _timedelta) -> str:
    """Shift the wall-clock time in an embedded DTSTART;TZID line by delta.

    When map_event embeds DTSTART;TZID=<tz>:<local> in the stored rrule, dateutil's
    rrulestr() prefers that DTSTART over the dtstart= kwarg.  After a scope=all move
    we must rewrite the embedded line so expand_recurring() uses the new time.

    Example:
        "DTSTART;TZID=America/New_York:20260209T090000\\nRRULE:FREQ=WEEKLY"
        + delta=timedelta(hours=5)
        → "DTSTART;TZID=America/New_York:20260209T140000\\nRRULE:FREQ=WEEKLY"

    If no embedded DTSTART;TZID is found the string is returned unchanged (bare
    RRULE strings — tether-native events or pre-Bug-1-fix GCal events — need no
    rewrite because expand_recurring() uses master start_time as dtstart).
    """
    import re as _re
    import zoneinfo as _zoneinfo

    m = _re.match(
        r'^(DTSTART;TZID=([^:]+):)(\d{8}T\d{6})([\s\S]*)$',
        rrule_str,
    )
    if not m:
        return rrule_str

    _prefix, tzid, dt_compact, rest = m.groups()
    try:
        tz = _zoneinfo.ZoneInfo(tzid)
    except (KeyError, _zoneinfo.ZoneInfoNotFoundError):
        return rrule_str  # unknown IANA name — leave unchanged

    old_local = _datetime.strptime(dt_compact, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
    new_local = old_local + delta
    new_compact = new_local.strftime("%Y%m%dT%H%M%S")
    return f"DTSTART;TZID={tzid}:{new_compact}{rest}"


async def update_event_time(
    conn: asyncpg.Connection,
    event_uuid: str,
    start_time: str,
    end_time: str,
    original_start_time: str | None = None,
) -> dict | None:
    """Reposition a calendar event to a new time slot.

    Only updates tasks that already have start_time set (i.e. are promoted events).
    Returns CalendarEvent-shaped dict, or None if not found / not an event.

    For recurring events (rrule IS NOT NULL), original_start_time is required —
    pass the ISO timestamp of the occurrence being dragged so the delta can be
    computed and applied to the master's start_time (and embedded DTSTART;TZID
    if present).  Omitting original_start_time on a recurring event raises
    ValueError to prevent silent corruption of the recurrence schedule.
    """
    if original_start_time is not None:
        return await _update_event_time_all(
            conn, event_uuid, start_time, end_time, original_start_time
        )

    # Guard: refuse to directly overwrite a recurring master without a delta.
    # The direct UPDATE would stamp the occurrence's date+time onto the master,
    # which destroys the recurrence anchor (Bug 2 original symptom).
    is_recurring = await conn.fetchval(
        "SELECT rrule IS NOT NULL FROM tasks WHERE uuid = $1 AND start_time IS NOT NULL",
        _uuid.UUID(event_uuid),
    )
    if is_recurring:
        raise ValueError(
            f"Task {event_uuid} is a recurring event — "
            "pass original_start_time to shift all occurrences safely"
        )

    row = await conn.fetchrow(
        """
        UPDATE tasks
        SET start_time = $1,
            end_time   = $2,
            version    = version + 1
        WHERE uuid = $3
          AND start_time IS NOT NULL
        RETURNING uuid, text, start_time, end_time, source, external_id, anchor_id, context_subject
        """,
        _parse_ts(start_time), _parse_ts(end_time), _uuid.UUID(event_uuid),
    )
    return _row_to_event(row) if row else None


# ---------------------------------------------------------------------------
# Recurrence scope edit DB functions
# ---------------------------------------------------------------------------


async def patch_recurring_this(
    conn,
    event_id: str,
    original_start_time: str,
    new_start_time: str,
    new_end_time: str,
) -> dict | None:
    """Edit a single occurrence of a recurring event ('this' scope).

    Steps (atomic):
    1. Fetch the master task row.  Return None if not found.
    2. Raise ValueError if the master has no rrule (not a recurring event).
    3. Append an EXDATE to the master's exdates[] to suppress the original slot.
    4. INSERT a new standalone event (no rrule) at the new time slot.
    5. Return the new standalone event as a CalendarEvent dict.

    *event_id* is the UUID of the recurring master.
    *original_start_time* is the ISO datetime of the occurrence being replaced
    (used to build the EXDATE token).
    """
    from datetime import timezone as _tz
    master_uuid = _uuid.UUID(event_id)
    original_dt = _parse_ts(original_start_time)
    new_start_dt = _parse_ts(new_start_time)
    new_end_dt = _parse_ts(new_end_time)

    async with conn.transaction():
        master = await conn.fetchrow(
            """
            SELECT uuid, text, start_time, end_time, source, external_id,
                   anchor_id, rrule, exdates, context_subject
            FROM tasks
            WHERE uuid = $1
              AND start_time IS NOT NULL
            """,
            master_uuid,
        )
        if master is None:
            return None

        if not master["rrule"]:
            raise ValueError(f"Task {event_id} is not a recurring event (rrule IS NULL)")

        # Build the EXDATE token for the suppressed occurrence
        if original_dt.tzinfo is None:
            original_dt = original_dt.replace(tzinfo=_tz.utc)
        exdate_token = "EXDATE:" + original_dt.strftime("%Y%m%dT%H%M%SZ")

        # 3. Append EXDATE to master
        await conn.execute(
            """
            UPDATE tasks
            SET exdates = array_append(exdates, $1),
                version = version + 1
            WHERE uuid = $2
            """,
            exdate_token, master_uuid,
        )

        # 4. INSERT standalone exception event (tether-native — source/external_id are nulled
        # to avoid the partial unique index on (user_id, source, external_id) WHERE source IS NOT NULL.
        # recurrence_id is set to master["external_id"] so get_events_for_range exception lookup
        # can suppress the ghost occurrence. For tether-native series (external_id IS NULL),
        # recurrence_id would also be NULL — exception suppression would not work in that case.
        # Known limitation: track separately when tether-native recurring series support is added.)
        new_row = await conn.fetchrow(
            """
            INSERT INTO tasks (
                uuid, user_id, text, status,
                start_time, end_time,
                anchor_id, context_subject,
                recurrence_id, original_start_time
            )
            VALUES (
                gen_random_uuid(),
                current_setting('app.current_user_id', true)::uuid,
                $1, 'pending',
                $2, $3,
                $4, $5,
                $6, $7
            )
            RETURNING uuid, text, start_time, end_time, source, external_id,
                      anchor_id, context_subject
            """,
            master["text"], new_start_dt, new_end_dt,
            master["anchor_id"], master["context_subject"],
            master["external_id"], original_dt,
        )

    return _row_to_event(new_row, is_recurring=False, is_occurrence=True) if new_row else None


async def patch_recurring_this_and_future(
    conn,
    event_id: str,
    original_start_time: str,
    new_start_time: str,
    new_end_time: str,
) -> dict | None:
    """Edit this and all future occurrences of a recurring event.

    Steps (atomic):
    1. Fetch the master task row.  Return None if not found.
    2. Raise ValueError if the master has no rrule.
    3. Truncate the master series: set UNTIL = original_dt - 1 second on its rrule.
    4. INSERT a new master task with the same rrule (stripped of UNTIL/COUNT)
       starting at new_start_time, with the series continuing from there.
    5. Return the new master as a CalendarEvent dict.

    *original_start_time* is the first occurrence being moved — the cutoff point.
    """
    from datetime import timezone as _tz
    master_uuid = _uuid.UUID(event_id)
    original_dt = _parse_ts(original_start_time)
    new_start_dt = _parse_ts(new_start_time)
    new_end_dt = _parse_ts(new_end_time)

    async with conn.transaction():
        master = await conn.fetchrow(
            """
            SELECT uuid, text, start_time, end_time, source, external_id,
                   anchor_id, rrule, exdates, context_subject
            FROM tasks
            WHERE uuid = $1
              AND start_time IS NOT NULL
            """,
            master_uuid,
        )
        if master is None:
            return None

        if not master["rrule"]:
            raise ValueError(f"Task {event_id} is not a recurring event (rrule IS NULL)")

        if original_dt.tzinfo is None:
            original_dt = original_dt.replace(tzinfo=_tz.utc)

        # 3. Set UNTIL = original_dt - 1 second on master (exclusive cutoff)
        until_dt = original_dt - _timedelta(seconds=1)
        truncated_rrule = _rrule_set_until(master["rrule"], until_dt)
        await conn.execute(
            """
            UPDATE tasks
            SET rrule = $1,
                version = version + 1
            WHERE uuid = $2
            """,
            truncated_rrule, master_uuid,
        )

        # 4. INSERT new master starting at new_start_time
        duration = (master["end_time"] - master["start_time"]) if (
            master["end_time"] and master["start_time"]
        ) else _timedelta(0)

        # Strip UNTIL/COUNT from the new master's rrule (open-ended series)
        import re as _re
        new_rrule = master["rrule"]
        prefix = ""
        value = new_rrule
        if new_rrule.upper().startswith("RRULE:"):
            prefix = new_rrule[:6]
            value = new_rrule[6:]
        value = _re.sub(r";?UNTIL=[^;]*", "", value, flags=_re.IGNORECASE)
        value = _re.sub(r";?COUNT=[^;]*", "", value, flags=_re.IGNORECASE)
        new_rrule = f"{prefix}{value.strip(';')}"

        # New master is tether-native (source/external_id nulled) to avoid the partial unique
        # index on (user_id, source, external_id) WHERE source IS NOT NULL.
        new_row = await conn.fetchrow(
            """
            INSERT INTO tasks (
                uuid, user_id, text, status,
                start_time, end_time,
                anchor_id, context_subject, rrule
            )
            VALUES (
                gen_random_uuid(),
                current_setting('app.current_user_id', true)::uuid,
                $1, 'pending',
                $2, $3,
                $4, $5, $6
            )
            RETURNING uuid, text, start_time, end_time, source, external_id,
                      anchor_id, context_subject
            """,
            master["text"], new_start_dt, new_end_dt,
            master["anchor_id"], master["context_subject"], new_rrule,
        )

    return _row_to_event(new_row, is_recurring=True, is_occurrence=False) if new_row else None


async def _update_event_time_all(
    conn: asyncpg.Connection,
    event_uuid: str,
    start_time: str,
    end_time: str,
    original_start_time: str,
) -> dict | None:
    """Shift an entire recurring series by the delta between the dragged occurrence
    and its new position.

    Logic:
      delta         = new_start − original_start_time (the occurrence being dragged)
      new_master    = master.start_time + delta
      new_master_end= master.end_time   + delta  (preserves duration)

    For GCal-synced events the stored rrule may contain an embedded DTSTART;TZID
    line (prepended by _prepend_dtstart_tzid in the mapping layer).  dateutil's
    rrulestr() treats that embedded DTSTART as authoritative and ignores the
    dtstart= kwarg.  We therefore also rewrite the embedded DTSTART by applying
    delta in the event's IANA timezone so expand_recurring() uses the new
    wall-clock time.

    Known limitation: the next inbound GCal sync will receive the original rrule
    from Google and _prepend_dtstart_tzid will rewrite the DTSTART back to the
    original time.  A scope=all move does not survive a sync cycle without an
    outbound push to GCal (not implemented — tracked as a follow-up).
    """
    occ_start_dt = _parse_ts(original_start_time)
    new_start_dt = _parse_ts(start_time)
    new_end_dt = _parse_ts(end_time)
    delta = new_start_dt - occ_start_dt

    master = await conn.fetchrow(
        """
        SELECT start_time, end_time, rrule
        FROM tasks
        WHERE uuid = $1
          AND start_time IS NOT NULL
        """,
        _uuid.UUID(event_uuid),
    )
    if not master:
        return None

    new_master_start = master["start_time"] + delta
    new_master_end = (master["end_time"] + delta) if master["end_time"] else new_end_dt

    # Rewrite any embedded DTSTART;TZID so rrulestr() uses the new wall-clock time.
    # For bare rrules (no DTSTART;TZID) this is a no-op.
    new_rrule = _rewrite_dtstart_in_rrule(master["rrule"] or "", delta)

    row = await conn.fetchrow(
        """
        UPDATE tasks
        SET start_time = $1,
            end_time   = $2,
            rrule      = $3,
            version    = version + 1
        WHERE uuid = $4
          AND start_time IS NOT NULL
        RETURNING uuid, text, start_time, end_time, source, external_id, anchor_id, context_subject
        """,
        new_master_start, new_master_end, new_rrule, _uuid.UUID(event_uuid),
    )
    return _row_to_event(row) if row else None
