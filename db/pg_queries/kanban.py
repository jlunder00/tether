"""Async Postgres queries — kanban_columns table."""
from __future__ import annotations

import uuid as _uuid

import asyncpg


async def seed_kanban_columns(conn: asyncpg.Connection) -> None:
    """Create default kanban columns for the current user if they have none. RLS scopes the count."""
    count = await conn.fetchval("SELECT COUNT(*) FROM kanban_columns")
    if count and count > 0:
        return

    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )

    defaults = [
        ("Backlog",      0, None,       {"plan_date": None, "status": "pending"},      {"set_status": "pending", "unschedule": True}),
        ("Pending",      1, "#3b82f6",  {"status": "pending", "plan_date": "not_null"},{"set_status": "pending", "prompt_schedule": True}),
        ("In Progress",  2, "#f59e0b",  {"status": "in_progress"},                     {"set_status": "in_progress"}),
        ("Done",         3, "#22c55e",  {"status": "done"},                             {"set_status": "done"}),
        ("Skipped",      4, "#94a3b8",  {"status": "skipped"},                         {"set_status": "skipped"}),
        ("Blocked",      5, "#ef4444",  {"status": "blocked"},                         {"set_status": "blocked"}),
    ]
    for name, position, color, match_rules, entry_rules in defaults:
        await conn.execute(
            """
            INSERT INTO kanban_columns (id, user_id, name, position, color, match_rules, entry_rules, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NULL)
            """,
            _uuid.uuid4(),
            user_uuid,
            name,
            position,
            color,
            match_rules,
            entry_rules,
        )


async def get_kanban_columns(conn: asyncpg.Connection) -> list[dict]:
    """Get columns for the current user. RLS scopes results to the user."""
    rows = await conn.fetch(
        """
        SELECT id, name, position, color, match_rules, entry_rules, created_by
        FROM kanban_columns
        ORDER BY position
        """
    )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "position": r["position"],
            "color": r["color"],
            "match_rules": r["match_rules"],  # already a dict from JSONB
            "entry_rules": r["entry_rules"],
            "created_by": r["created_by"],
        }
        for r in rows
    ]


async def create_kanban_column(
    conn: asyncpg.Connection,
    name: str,
    position: int,
    color: str | None,
    match_rules: dict,
    entry_rules: dict,
) -> dict:
    col_id = _uuid.uuid4()
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    await conn.execute(
        """
        INSERT INTO kanban_columns (id, user_id, name, position, color, match_rules, entry_rules, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        col_id,
        user_uuid,
        name,
        position,
        color,
        match_rules,
        entry_rules,
        str(user_uuid),
    )
    return {
        "id": str(col_id),
        "name": name,
        "position": position,
        "color": color,
        "match_rules": match_rules,
        "entry_rules": entry_rules,
        "created_by": str(user_uuid),
    }


async def update_kanban_column(
    conn: asyncpg.Connection, column_id: str, fields: dict
) -> dict | None:
    allowed = {"name", "position", "color", "match_rules", "entry_rules"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None

    params = list(updates.values())
    params.append(column_id)
    set_clause = ", ".join(f"{k} = ${i + 1}" for i, k in enumerate(updates))

    await conn.execute(
        f"UPDATE kanban_columns SET {set_clause} WHERE id = ${len(params)}",
        *params,
    )
    row = await conn.fetchrow(
        "SELECT id, name, position, color, match_rules, entry_rules, created_by"
        " FROM kanban_columns WHERE id = $1",
        column_id,
    )
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "position": row["position"],
        "color": row["color"],
        "match_rules": row["match_rules"],
        "entry_rules": row["entry_rules"],
        "created_by": str(row["created_by"]) if row["created_by"] else None,
    }


async def delete_kanban_column(conn: asyncpg.Connection, column_id: str) -> None:
    await conn.execute("DELETE FROM kanban_columns WHERE id = $1", column_id)


async def migrate_backlog_column(conn: asyncpg.Connection) -> None:
    """Tighten Backlog match_rules and add unschedule entry_rule (fixes drag-drop)."""
    await conn.execute(
        "UPDATE kanban_columns SET match_rules = $1, entry_rules = $2 WHERE id = 'col_backlog'",
        {"plan_date": None, "status": "pending"},
        {"set_status": "pending", "unschedule": True},
    )
