"""Async Postgres queries — context_nodes and node_tasks."""
from __future__ import annotations
import uuid as _uuid

import asyncpg


def _node(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    for f in ("id", "parent_id", "context_node_id"):
        if f in d and d[f] is not None:
            d[f] = str(d[f])
    return d


async def create_node(
    conn: asyncpg.Connection,
    parent_id: str | None,
    name: str,
    node_type: str = "context",
    target_date: str | None = None,
    status: str = "pending",
    status_override: bool = False,
    color: str | None = None,
    description: str | None = None,
) -> dict:
    if node_type not in ("context", "milestone"):
        raise ValueError(f"Invalid node_type: {node_type!r}")
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    pid = _uuid.UUID(parent_id) if parent_id else None
    row = await conn.fetchrow(
        """
        INSERT INTO context_nodes
            (user_id, parent_id, name, node_type, description, target_date,
             status, status_override, color)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING *
        """,
        user_uuid, pid, name, node_type, description, target_date,
        status, status_override, color,
    )
    return _node(row)


async def get_node(conn: asyncpg.Connection, node_id: str) -> dict | None:
    row = await conn.fetchrow(
        "SELECT * FROM context_nodes WHERE id = $1", _uuid.UUID(node_id)
    )
    if not row:
        return None
    d = _node(row)
    sections = await conn.fetch(
        "SELECT DISTINCT section_type FROM node_sections WHERE node_id = $1 ORDER BY section_type",
        _uuid.UUID(node_id),
    )
    d["section_types"] = [s["section_type"] for s in sections]
    d["children_count"] = await conn.fetchval(
        "SELECT COUNT(*) FROM context_nodes WHERE parent_id = $1", _uuid.UUID(node_id)
    )
    return d


async def get_node_by_path(conn: asyncpg.Connection, path: str) -> dict | None:
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    row = await conn.fetchrow(
        "SELECT id FROM context_nodes WHERE parent_id IS NULL AND name = $1", parts[0]
    )
    if not row:
        return None
    resolved_id = row["id"]
    for segment in parts[1:]:
        row = await conn.fetchrow(
            "SELECT id FROM context_nodes WHERE parent_id = $1 AND name = $2",
            resolved_id, segment,
        )
        if not row:
            return None
        resolved_id = row["id"]
    return await get_node(conn, str(resolved_id))


async def find_child_by_name(
    conn: asyncpg.Connection, parent_id: str | None, name: str
) -> dict | None:
    if parent_id is None:
        row = await conn.fetchrow(
            "SELECT * FROM context_nodes WHERE parent_id IS NULL AND name = $1", name
        )
    else:
        row = await conn.fetchrow(
            "SELECT * FROM context_nodes WHERE parent_id = $1 AND name = $2",
            _uuid.UUID(parent_id), name,
        )
    return _node(row)


async def get_node_path(conn: asyncpg.Connection, node_id: str) -> str | None:
    rows = await conn.fetch(
        """
        WITH RECURSIVE ancestors(id, parent_id, name, depth) AS (
            SELECT id, parent_id, name, 0 FROM context_nodes WHERE id = $1
            UNION ALL
            SELECT cn.id, cn.parent_id, cn.name, a.depth + 1
            FROM context_nodes cn
            JOIN ancestors a ON cn.id = a.parent_id
        )
        SELECT name FROM ancestors ORDER BY depth DESC
        """,
        _uuid.UUID(node_id),
    )
    if not rows:
        return None
    return "/".join(r["name"] for r in rows)


async def ensure_node_path(conn: asyncpg.Connection, path: str) -> dict:
    parts = [p.strip() for p in path.split("/") if p.strip()]
    if not parts:
        raise ValueError("ensure_node_path: empty path")
    parent_id = None
    node = None
    for part in parts:
        existing = await find_child_by_name(conn, parent_id, part)
        if existing:
            node = existing
        else:
            node = await create_node(conn, parent_id, part)
        parent_id = node["id"]
    return await get_node(conn, node["id"])


async def get_all_node_paths(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        """
        WITH RECURSIVE tree(id, path) AS (
            SELECT id, name FROM context_nodes
            WHERE parent_id IS NULL AND archived = FALSE
            UNION ALL
            SELECT cn.id, tree.path || '/' || cn.name
            FROM context_nodes cn
            JOIN tree ON cn.parent_id = tree.id
            WHERE cn.archived = FALSE
        )
        SELECT path FROM tree ORDER BY path
        """
    )
    return [r["path"] for r in rows]


async def get_children(
    conn: asyncpg.Connection,
    parent_id: str | None = None,
    include_archived: bool = False,
) -> list[dict]:
    if parent_id is None:
        if include_archived:
            rows = await conn.fetch(
                "SELECT * FROM context_nodes WHERE parent_id IS NULL ORDER BY name"
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM context_nodes WHERE parent_id IS NULL AND archived = FALSE ORDER BY name"
            )
    else:
        pid = _uuid.UUID(parent_id)
        if include_archived:
            rows = await conn.fetch(
                "SELECT * FROM context_nodes WHERE parent_id = $1 ORDER BY name", pid
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM context_nodes WHERE parent_id = $1 AND archived = FALSE ORDER BY name",
                pid,
            )
    return [_node(r) for r in rows]


async def get_subtree(
    conn: asyncpg.Connection, node_id: str, include_archived: bool = False
) -> list[dict]:
    archived_filter = "" if include_archived else " AND cn.archived = FALSE"
    rows = await conn.fetch(
        f"""
        WITH RECURSIVE descendants(id) AS (
            SELECT id FROM context_nodes WHERE parent_id = $1
            UNION ALL
            SELECT cn.id FROM context_nodes cn
            JOIN descendants d ON cn.parent_id = d.id{archived_filter}
        )
        SELECT cn.* FROM context_nodes cn
        JOIN descendants d ON cn.id = d.id
        ORDER BY cn.name
        """,
        _uuid.UUID(node_id),
    )
    return [_node(r) for r in rows]


async def move_node(conn: asyncpg.Connection, node_id: str, new_parent_id: str | None) -> None:
    uid = _uuid.UUID(node_id)
    if new_parent_id is not None:
        if new_parent_id == node_id:
            raise ValueError("Cannot move a node under itself.")
        ancestors = await conn.fetch(
            """
            WITH RECURSIVE ancestors(id) AS (
                SELECT parent_id FROM context_nodes WHERE id = $1
                UNION ALL
                SELECT cn.parent_id FROM context_nodes cn
                JOIN ancestors a ON cn.id = a.id
                WHERE cn.parent_id IS NOT NULL
            )
            SELECT id FROM ancestors
            """,
            _uuid.UUID(new_parent_id),
        )
        if any(str(a["id"]) == node_id for a in ancestors):
            raise ValueError("Cannot move a node under one of its own descendants.")
    pid = _uuid.UUID(new_parent_id) if new_parent_id else None
    await conn.execute(
        "UPDATE context_nodes SET parent_id = $1, updated_at = now(), version = version + 1 WHERE id = $2",
        pid, uid,
    )


async def rename_node(conn: asyncpg.Connection, node_id: str, new_name: str) -> None:
    await conn.execute(
        "UPDATE context_nodes SET name = $1, updated_at = now(), version = version + 1 WHERE id = $2",
        new_name, _uuid.UUID(node_id),
    )


async def delete_node(conn: asyncpg.Connection, node_id: str) -> None:
    await conn.execute("DELETE FROM context_nodes WHERE id = $1", _uuid.UUID(node_id))


async def archive_node(conn: asyncpg.Connection, node_id: str) -> None:
    await conn.execute(
        "UPDATE context_nodes SET archived = TRUE, updated_at = now() WHERE id = $1",
        _uuid.UUID(node_id),
    )


async def unarchive_node(conn: asyncpg.Connection, node_id: str) -> None:
    await conn.execute(
        "UPDATE context_nodes SET archived = FALSE, updated_at = now() WHERE id = $1",
        _uuid.UUID(node_id),
    )


async def patch_node_fields(
    conn: asyncpg.Connection, node_id: str, fields: dict
) -> dict | None:
    allowed = {"name", "target_date", "status", "color", "archived", "description"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return await get_node(conn, node_id)
    if "status" in updates:
        updates["status_override"] = True
    updates["updated_at"] = "now()"  # handled below as literal
    updates["version"] = None        # placeholder

    params = []
    set_parts = []
    for k, v in updates.items():
        if v == "now()":
            set_parts.append(f"{k} = now()")
        elif k == "version":
            set_parts.append("version = version + 1")
        else:
            params.append(v)
            set_parts.append(f"{k} = ${len(params)}")
    params.append(_uuid.UUID(node_id))
    await conn.execute(
        f"UPDATE context_nodes SET {', '.join(set_parts)} WHERE id = ${len(params)}",
        *params,
    )
    return await get_node(conn, node_id)


async def get_auto_archivable_nodes(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT * FROM context_nodes
        WHERE target_date IS NOT NULL
          AND target_date::date < now()::date
          AND archived = FALSE
          AND status = 'done'
        """
    )
    return [_node(r) for r in rows]


async def get_milestone_nodes(
    conn: asyncpg.Connection,
    parent_id: str | None = None,
    include_archived: bool = False,
) -> list[dict]:
    conditions = ["cn.node_type = 'milestone'"]
    params: list = []
    if parent_id is not None:
        params.append(_uuid.UUID(parent_id))
        conditions.append(f"cn.parent_id = ${len(params)}")
    if not include_archived:
        conditions.append("cn.archived = FALSE")
    where = " AND ".join(conditions)
    rows = await conn.fetch(
        f"""
        SELECT cn.*,
               COUNT(nt.task_id) AS task_count,
               SUM(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) AS done_count
        FROM context_nodes cn
        LEFT JOIN node_tasks nt ON nt.node_id = cn.id
        LEFT JOIN tasks t ON t.uuid::text = nt.task_id
        WHERE {where}
        GROUP BY cn.id
        ORDER BY cn.name
        """,
        *params,
    )
    return [_node(r) for r in rows]


# ── Node-task linking ─────────────────────────────────────────────────────────

async def link_task_to_node(conn: asyncpg.Connection, node_id: str, task_id: str) -> None:
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    await conn.execute(
        "INSERT INTO node_tasks (node_id, task_id, user_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
        node_id, task_id, user_uuid,
    )


async def unlink_task_from_node(conn: asyncpg.Connection, node_id: str, task_id: str) -> None:
    await conn.execute(
        "DELETE FROM node_tasks WHERE node_id = $1 AND task_id = $2", node_id, task_id
    )


async def get_node_tasks(conn: asyncpg.Connection, node_id: str) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT t.uuid, t.text, t.status, t.plan_date, t.anchor_id
        FROM node_tasks nt
        JOIN tasks t ON t.uuid::text = nt.task_id
        WHERE nt.node_id = $1
        ORDER BY t.plan_date DESC NULLS LAST, t.text
        """,
        node_id,
    )
    return [
        {"id": str(r["uuid"]), "text": r["text"], "status": r["status"],
         "plan_date": r["plan_date"], "anchor_id": str(r["anchor_id"]) if r["anchor_id"] else None}
        for r in rows
    ]


async def get_task_nodes(conn: asyncpg.Connection, task_id: str) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT cn.* FROM context_nodes cn
        JOIN node_tasks nt ON nt.node_id = cn.id::text
        WHERE nt.task_id = $1
        ORDER BY cn.name
        """,
        task_id,
    )
    return [_node(r) for r in rows]
