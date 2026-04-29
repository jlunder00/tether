"""Async Postgres queries — milestones (legacy table, not context_nodes milestones)."""
from __future__ import annotations
from collections import defaultdict
import uuid as _uuid

import asyncpg

from db.pg_queries.errors import StaleReadError
from db.pg_queries._motif import validate_motif


def _derive_milestone_status(statuses: list[str]) -> str:
    if not statuses:
        return "pending"
    if all(s == "done" for s in statuses):
        return "done"
    if any(s == "blocked" for s in statuses) and not any(s == "in_progress" for s in statuses):
        return "blocked"
    if any(s in ("in_progress", "done") for s in statuses):
        return "in_progress"
    return "pending"


async def create_milestone(
    conn: asyncpg.Connection,
    context_subject: str,
    name: str,
    description: str | None = None,
    target_date: str | None = None,
    color: str | None = None,
    motif: str = "anchor",
) -> dict:
    validate_motif(motif)
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    # Resolve context_entry_id from subject
    entry_id = await conn.fetchval(
        "SELECT id FROM context_entries WHERE subject = $1", context_subject
    )
    row = await conn.fetchrow(
        """
        INSERT INTO milestones
            (id, user_id, context_entry_id, name, description, target_date, color, motif)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, name, description, target_date, color, motif, status, status_override,
                  created_at, updated_at, version
        """,
        _uuid.uuid4(), user_uuid, entry_id, name, description, target_date, color, motif,
    )
    return {
        "id": str(row["id"]),
        "context_subject": context_subject,
        "name": row["name"],
        "description": row["description"],
        "target_date": row["target_date"],
        "color": row["color"],
        "motif": row["motif"],
        "status": "pending",
        "status_override": False,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "task_count": 0,
        "done_count": 0,
        "task_ids": [],
        "tasks": [],
    }


async def get_milestones(
    conn: asyncpg.Connection, context_subject: str | None = None
) -> list[dict]:
    if context_subject is not None:
        rows = await conn.fetch(
            """
            SELECT m.*, ce.subject AS context_subject
            FROM milestones m
            LEFT JOIN context_entries ce ON ce.id = m.context_entry_id
            WHERE ce.subject = $1
            ORDER BY m.created_at
            """,
            context_subject,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT m.*, ce.subject AS context_subject
            FROM milestones m
            LEFT JOIN context_entries ce ON ce.id = m.context_entry_id
            ORDER BY ce.subject, m.created_at
            """
        )
    if not rows:
        return []

    ids = [r["id"] for r in rows]
    links = await conn.fetch(
        """
        SELECT mt.milestone_id, mt.task_id,
               COALESCE(t.status, 'pending') AS task_status,
               t.text AS task_text, t.plan_date, t.anchor_id
        FROM milestone_tasks mt
        LEFT JOIN tasks t ON t.uuid::text = mt.task_id
        WHERE mt.milestone_id = ANY($1)
        """,
        ids,
    )

    task_ids_map: dict = defaultdict(list)
    tasks_map: dict = defaultdict(list)
    statuses_map: dict = defaultdict(list)
    for link in links:
        mid = link["milestone_id"]
        task_ids_map[mid].append(link["task_id"])
        statuses_map[mid].append(link["task_status"])
        tasks_map[mid].append({
            "id": link["task_id"],
            "text": link["task_text"],
            "status": link["task_status"],
            "plan_date": link["plan_date"],
            "anchor_id": str(link["anchor_id"]) if link["anchor_id"] else None,
        })

    result = []
    for m in rows:
        mid = m["id"]
        statuses = statuses_map[mid]
        result.append({
            "id": str(mid),
            "context_subject": m["context_subject"],
            "name": m["name"],
            "description": m["description"],
            "target_date": m["target_date"],
            "color": m["color"],
            "motif": m["motif"],
            "status": m["status"] if m["status_override"] else _derive_milestone_status(statuses),
            "status_override": bool(m["status_override"]),
            "created_at": m["created_at"],
            "updated_at": m["updated_at"],
            "version": m["version"],
            "task_count": len(statuses),
            "done_count": sum(1 for s in statuses if s == "done"),
            "task_ids": task_ids_map[mid],
            "tasks": tasks_map[mid],
        })
    return result


async def patch_milestone(
    conn: asyncpg.Connection,
    milestone_id: str,
    fields: dict,
    expected_version: int | None = None,
) -> dict | None:
    # Build SET clause from static column-name literals only.
    params: list = []
    set_parts: list[str] = []

    if "name" in fields:
        params.append(fields["name"])
        set_parts.append(f"name = ${len(params)}")
    if "description" in fields:
        params.append(fields["description"])
        set_parts.append(f"description = ${len(params)}")
    if "target_date" in fields:
        params.append(fields["target_date"])
        set_parts.append(f"target_date = ${len(params)}")
    if "color" in fields:
        params.append(fields["color"])
        set_parts.append(f"color = ${len(params)}")
    if "motif" in fields:
        validate_motif(fields["motif"])
        params.append(fields["motif"])
        set_parts.append(f"motif = ${len(params)}")
    if "status" in fields:
        params.append(fields["status"])
        set_parts.append(f"status = ${len(params)}")
        params.append(True)
        set_parts.append(f"status_override = ${len(params)}")

    if not set_parts:
        return None

    set_parts.extend(["updated_at = now()", "version = version + 1"])

    if expected_version is not None:
        params.append(expected_version)
        where = f"id = ${len(params) + 1} AND version = ${len(params)}"
    else:
        where = f"id = ${len(params) + 1}"
    params.append(_uuid.UUID(milestone_id))

    result = await conn.execute(
        f"UPDATE milestones SET {', '.join(set_parts)} WHERE {where}", *params
    )
    if result == "UPDATE 0" and expected_version is not None:
        current = await conn.fetchval(
            "SELECT version FROM milestones WHERE id = $1", _uuid.UUID(milestone_id)
        )
        if current is None:
            return None
        raise StaleReadError(current)
    if result == "UPDATE 0":
        return None

    row = await conn.fetchrow(
        "SELECT ce.subject AS context_subject FROM milestones m LEFT JOIN context_entries ce ON ce.id = m.context_entry_id WHERE m.id = $1",
        _uuid.UUID(milestone_id),
    )
    subject = row["context_subject"] if row else None
    milestones = await get_milestones(conn, subject)
    return next((m for m in milestones if m["id"] == milestone_id), None)


async def delete_milestone(conn: asyncpg.Connection, milestone_id: str) -> None:
    await conn.execute("DELETE FROM milestones WHERE id = $1", _uuid.UUID(milestone_id))


async def link_milestone_task(
    conn: asyncpg.Connection, milestone_id: str, task_id: str
) -> None:
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    await conn.execute(
        "INSERT INTO milestone_tasks (milestone_id, task_id, user_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
        _uuid.UUID(milestone_id), task_id, user_uuid,
    )


async def unlink_milestone_task(
    conn: asyncpg.Connection, milestone_id: str, task_id: str
) -> None:
    await conn.execute(
        "DELETE FROM milestone_tasks WHERE milestone_id = $1 AND task_id = $2",
        _uuid.UUID(milestone_id), task_id,
    )
