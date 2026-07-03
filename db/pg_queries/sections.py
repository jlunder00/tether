"""Async Postgres queries — node_sections (FTS via tsvector)."""
from __future__ import annotations
import uuid as _uuid

import asyncpg


async def get_sections(conn: asyncpg.Connection, node_id: str) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT section_type, name, body, position, version, updated_at,
               origin, visible_to_user
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
        SELECT section_type, name, body, position, version, updated_at,
               origin, visible_to_user
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
    *,
    origin: str = "user",
    visible_to_user: bool = True,
) -> dict:
    """Insert or replace a node section.

    origin: 'user' | 'conversation_agent' | 'system' — who authored this section.
    visible_to_user: False hides the section from user-facing reads.
    """
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
        INSERT INTO node_sections
            (user_id, node_id, section_type, name, body, position,
             origin, visible_to_user, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
        ON CONFLICT (node_id, section_type, name) DO UPDATE
            SET body           = EXCLUDED.body,
                origin         = EXCLUDED.origin,
                visible_to_user = EXCLUDED.visible_to_user,
                updated_at     = now(),
                version        = node_sections.version + 1
        RETURNING section_type, name, body, version, updated_at, origin, visible_to_user
        """,
        user_uuid, nid, section_type, name, body, next_pos, origin, visible_to_user,
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
    *,
    origin: str = "user",
    visible_to_user: bool = True,
) -> dict:
    """Append content to an existing section (or create it). Preserves existing body."""
    existing = await get_section(conn, node_id, section_type, name=name)
    if existing and existing["body"]:
        new_body = existing["body"] + "\n\n" + content
    else:
        new_body = content
    return await upsert_section(
        conn, node_id, section_type, new_body, name=name,
        origin=origin, visible_to_user=visible_to_user,
    )


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


async def grep_sections(
    conn: asyncpg.Connection,
    pattern: str,
    node_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    """ILIKE text search over node section bodies.

    pattern: SQL ILIKE pattern (caller wraps in % if needed).
    node_ids: Optional list of node UUID strings to restrict results.
    limit:    Max rows returned (capped at 100 by callers).

    Returns list of dicts: {node_id, node_name, section_type, section_name,
                             snippet, origin, visible_to_user}.
    """
    if node_ids:
        rows = await conn.fetch(
            """
            SELECT
                ns.node_id::text,
                cn.name AS node_name,
                ns.section_type,
                ns.name AS section_name,
                left(ns.body, 300) AS snippet,
                ns.origin,
                ns.visible_to_user
            FROM node_sections ns
            JOIN context_nodes cn ON cn.id = ns.node_id
            WHERE ns.node_id = ANY($1::uuid[])
              AND ns.body ILIKE $2
            ORDER BY cn.name, ns.section_type, ns.name
            LIMIT $3
            """,
            node_ids, pattern, limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT
                ns.node_id::text,
                cn.name AS node_name,
                ns.section_type,
                ns.name AS section_name,
                left(ns.body, 300) AS snippet,
                ns.origin,
                ns.visible_to_user
            FROM node_sections ns
            JOIN context_nodes cn ON cn.id = ns.node_id
            WHERE ns.body ILIKE $1
            ORDER BY cn.name, ns.section_type, ns.name
            LIMIT $2
            """,
            pattern, limit,
        )
    return [
        {
            "node_id": r["node_id"],
            "node_name": r["node_name"],
            "section_type": r["section_type"],
            "section_name": r["section_name"],
            "snippet": r["snippet"],
            "origin": r["origin"],
            "visible_to_user": r["visible_to_user"],
        }
        for r in rows
    ]


async def search_sections_fts(
    conn: asyncpg.Connection,
    query: str,
    node_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    """Full-text search over node section bodies using Postgres tsvector.

    Uses the trigger-maintained search_vector column (GIN-indexed).
    Returns results ordered by ts_rank descending (most relevant first).

    query:    Natural language search terms (passed to plainto_tsquery).
    node_ids: Optional list of node UUID strings to restrict search.
    limit:    Max rows returned (capped at caller's discretion).

    Returns list of dicts: {node_id, node_name, section_type, section_name,
                             snippet, score}.
    """
    if node_ids:
        rows = await conn.fetch(
            """
            SELECT
                ns.node_id,
                cn.name AS node_name,
                ns.section_type,
                ns.name AS section_name,
                ts_headline(
                    'english', ns.body,
                    plainto_tsquery('english', $1),
                    'StartSel=<b>, StopSel=</b>, MaxWords=30, MinWords=10'
                ) AS snippet,
                ts_rank(ns.search_vector, plainto_tsquery('english', $1)) AS score
            FROM node_sections ns
            JOIN context_nodes cn ON cn.id = ns.node_id
            WHERE ns.search_vector @@ plainto_tsquery('english', $1)
              AND ns.node_id = ANY($2::uuid[])
            ORDER BY score DESC
            LIMIT $3
            """,
            query, node_ids, limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT
                ns.node_id,
                cn.name AS node_name,
                ns.section_type,
                ns.name AS section_name,
                ts_headline(
                    'english', ns.body,
                    plainto_tsquery('english', $1),
                    'StartSel=<b>, StopSel=</b>, MaxWords=30, MinWords=10'
                ) AS snippet,
                ts_rank(ns.search_vector, plainto_tsquery('english', $1)) AS score
            FROM node_sections ns
            JOIN context_nodes cn ON cn.id = ns.node_id
            WHERE ns.search_vector @@ plainto_tsquery('english', $1)
            ORDER BY score DESC
            LIMIT $2
            """,
            query, limit,
        )
    return [
        {
            "node_id": str(r["node_id"]),
            "node_name": r["node_name"],
            "section_type": r["section_type"],
            "section_name": r["section_name"],
            "snippet": r["snippet"],
            "score": float(r["score"]),
        }
        for r in rows
    ]
