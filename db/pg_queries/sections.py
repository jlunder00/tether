"""Async Postgres queries — node_sections (FTS via tsvector)."""
from __future__ import annotations
import uuid as _uuid

import asyncpg


async def get_sections(conn: asyncpg.Connection, node_id: str) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT section_type, name, body, position, version, updated_at
        FROM node_sections WHERE node_id = $1
        ORDER BY section_type, position
        """,
        _uuid.UUID(node_id),
    )
    return [dict(r) for r in rows]


async def get_section(
    conn: asyncpg.Connection, node_id: str, section_type: str, name: str = "main"
) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT section_type, name, body, position, version, updated_at
        FROM node_sections
        WHERE node_id = $1 AND section_type = $2 AND name = $3
        """,
        _uuid.UUID(node_id), section_type, name,
    )
    return dict(row) if row else None


async def upsert_section(
    conn: asyncpg.Connection,
    node_id: str,
    section_type: str,
    body: str,
    name: str = "main",
) -> dict:
    nid = _uuid.UUID(node_id)
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    next_pos = await conn.fetchval(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM node_sections WHERE node_id = $1 AND section_type = $2",
        nid, section_type,
    )
    row = await conn.fetchrow(
        """
        INSERT INTO node_sections (user_id, node_id, section_type, name, body, position, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, now())
        ON CONFLICT (node_id, section_type, name) DO UPDATE
            SET body = EXCLUDED.body, updated_at = now(), version = node_sections.version + 1
        RETURNING section_type, name, body, version, updated_at
        """,
        user_uuid, nid, section_type, name, body, next_pos,
    )
    await conn.execute(
        "UPDATE context_nodes SET updated_at = now() WHERE id = $1", nid
    )
    return dict(row)


async def append_section(
    conn: asyncpg.Connection,
    node_id: str,
    section_type: str,
    content: str,
    name: str = "main",
) -> dict:
    existing = await get_section(conn, node_id, section_type, name=name)
    if existing and existing["body"]:
        new_body = existing["body"] + "\n\n" + content
    else:
        new_body = content
    return await upsert_section(conn, node_id, section_type, new_body, name=name)


async def delete_section(
    conn: asyncpg.Connection, node_id: str, section_type: str, name: str = "main"
) -> None:
    await conn.execute(
        "DELETE FROM node_sections WHERE node_id = $1 AND section_type = $2 AND name = $3",
        _uuid.UUID(node_id), section_type, name,
    )


async def list_section_files(
    conn: asyncpg.Connection, node_id: str, section_type: str
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT name, length(body) AS size, position, updated_at
        FROM node_sections
        WHERE node_id = $1 AND section_type = $2
        ORDER BY position
        """,
        _uuid.UUID(node_id), section_type,
    )
    return [dict(r) for r in rows]


async def create_section_file(
    conn: asyncpg.Connection,
    node_id: str,
    section_type: str,
    name: str,
    body: str = "",
) -> dict:
    nid = _uuid.UUID(node_id)
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )
    position = await conn.fetchval(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM node_sections WHERE node_id = $1 AND section_type = $2",
        nid, section_type,
    )
    row = await conn.fetchrow(
        """
        INSERT INTO node_sections (user_id, node_id, section_type, name, body, position, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, now())
        RETURNING section_type, name, body, position, updated_at
        """,
        user_uuid, nid, section_type, name, body, position,
    )
    await conn.execute("UPDATE context_nodes SET updated_at = now() WHERE id = $1", nid)
    return dict(row)


async def rename_section_file(
    conn: asyncpg.Connection,
    node_id: str,
    section_type: str,
    old_name: str,
    new_name: str,
) -> dict:
    nid = _uuid.UUID(node_id)
    try:
        result = await conn.execute(
            """
            UPDATE node_sections SET name = $1, updated_at = now()
            WHERE node_id = $2 AND section_type = $3 AND name = $4
            """,
            new_name, nid, section_type, old_name,
        )
    except asyncpg.UniqueViolationError:
        raise ValueError(f"Section file '{new_name}' already exists in {section_type}")
    if result == "UPDATE 0":
        raise ValueError(f"Section file '{old_name}' not found in {section_type}")
    await conn.execute("UPDATE context_nodes SET updated_at = now() WHERE id = $1", nid)
    return await get_section(conn, node_id, section_type, name=new_name)


async def reorder_section_files(
    conn: asyncpg.Connection,
    node_id: str,
    section_type: str,
    name_order: list[str],
) -> None:
    nid = _uuid.UUID(node_id)
    existing = await conn.fetch(
        "SELECT name FROM node_sections WHERE node_id = $1 AND section_type = $2",
        nid, section_type,
    )
    existing_names = {r["name"] for r in existing}
    order_set = set(name_order)
    unknown = order_set - existing_names
    if unknown:
        raise ValueError(f"Names not found in {section_type}: {unknown}")
    missing = existing_names - order_set
    if missing:
        raise ValueError(f"Existing files omitted from ordering: {missing}")
    for position, name in enumerate(name_order):
        await conn.execute(
            "UPDATE node_sections SET position = $1, updated_at = now() WHERE node_id = $2 AND section_type = $3 AND name = $4",
            position, nid, section_type, name,
        )
    await conn.execute("UPDATE context_nodes SET updated_at = now() WHERE id = $1", nid)


async def search_sections(
    conn: asyncpg.Connection, query: str, node_id: str | None = None
) -> list[dict]:
    """FTS search using Postgres tsvector. Returns [{node_id, section_type, name, snippet}]."""
    if node_id is not None:
        subtree_ids = await conn.fetch(
            """
            WITH RECURSIVE descendants(id) AS (
                SELECT $1::uuid
                UNION ALL
                SELECT cn.id FROM context_nodes cn
                JOIN descendants d ON cn.parent_id = d.id
            )
            SELECT id FROM descendants
            """,
            _uuid.UUID(node_id),
        )
        id_list = [r["id"] for r in subtree_ids]
        if not id_list:
            return []
        rows = await conn.fetch(
            """
            SELECT ns.node_id, ns.section_type, ns.name,
                   ts_headline('english', ns.body,
                       plainto_tsquery('english', $1),
                       'StartSel=<b>, StopSel=</b>, MaxWords=15, MinWords=5') AS snippet
            FROM node_sections ns
            WHERE ns.search_vector @@ plainto_tsquery('english', $1)
              AND ns.node_id = ANY($2)
            ORDER BY ts_rank(ns.search_vector, plainto_tsquery('english', $1)) DESC
            """,
            query, id_list,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT ns.node_id, ns.section_type, ns.name,
                   ts_headline('english', ns.body,
                       plainto_tsquery('english', $1),
                       'StartSel=<b>, StopSel=</b>, MaxWords=15, MinWords=5') AS snippet
            FROM node_sections ns
            WHERE ns.search_vector @@ plainto_tsquery('english', $1)
            ORDER BY ts_rank(ns.search_vector, plainto_tsquery('english', $1)) DESC
            """,
            query,
        )
    return [
        {"node_id": str(r["node_id"]), "section_type": r["section_type"],
         "name": r["name"], "snippet": r["snippet"]}
        for r in rows
    ]
