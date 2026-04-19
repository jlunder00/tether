"""Async Postgres queries — tasks, subtasks, and dependencies."""
from __future__ import annotations
import uuid as _uuid

import asyncpg

from db.pg_queries.errors import StaleReadError
from db.pg_queries.plans import _row_to_task


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
    allowed = {"text", "status", "position", "followup_config", "description",
               "context_subject", "plan_date", "anchor_id"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None

    # anchor_id is stored as UUID
    if "anchor_id" in updates and updates["anchor_id"] is not None:
        updates["anchor_id"] = _uuid.UUID(updates["anchor_id"])

    params = list(updates.values())
    set_parts = [f"{k} = ${i + 1}" for i, k in enumerate(updates)]
    set_parts.append(f"version = version + 1")

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
    allowed = {"text", "done", "position"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    if "done" in updates:
        updates["done"] = bool(updates["done"])
    params = list(updates.values())
    params.append(subtask_id)
    set_clause = ", ".join(f"{k} = ${i + 1}" for i, k in enumerate(updates))
    await conn.execute(f"UPDATE subtasks SET {set_clause} WHERE id = ${len(params)}", *params)


async def delete_subtask(conn: asyncpg.Connection, subtask_id: int) -> None:
    await conn.execute("DELETE FROM subtasks WHERE id = $1", subtask_id)


async def reorder_subtasks(conn: asyncpg.Connection, task_id: str, id_order: list[int]) -> None:
    for pos, subtask_id in enumerate(id_order):
        await conn.execute(
            "UPDATE subtasks SET position = $1 WHERE id = $2 AND task_id = $3",
            pos, subtask_id, task_id,
        )
