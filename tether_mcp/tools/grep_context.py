"""grep_context MCP tool — text search over node sections.

Uses Postgres ILIKE for simple substring matches and tsvector GIN index for
full-text queries. Results are returned with node context so the bot knows
where each match lives in the tree.

v1 scope:
  ILIKE search over node_sections.body (simple, reliable, no stemming).
  The existing tsvector GIN index on node_sections.search_vector is used
  when ts_query mode is requested (mode='fts').

Scope filtering:
  paths — list of node paths (resolved to subtrees); if empty, searches all
          nodes accessible to the current user via RLS.
"""
from __future__ import annotations

import asyncpg


async def execute_grep_context(
    conn: asyncpg.Connection,
    pattern: str,
    scope: str = "user",
    paths: list[str] | None = None,
    limit: int = 20,
) -> dict:
    """Search node sections for a text pattern.

    Args:
        conn:    asyncpg connection (user-scoped via RLS).
        pattern: Search string. Use % for ILIKE wildcards, or plain text
                 for substring match (automatically wrapped in %).
        scope:   'user' (default) — search user's own nodes only (RLS enforced).
        paths:   Optional list of node paths to restrict search to their subtrees.
        limit:   Max results (default 20, max 100).

    Returns:
        {matches: [{node_id, node_name, path, section_type, name, snippet}], total}
    """
    from db.pg_queries.context import get_node_by_path

    if not pattern or not pattern.strip():
        return {"error": "pattern_required"}

    limit = min(limit, 100)

    # Normalize pattern: if no % wildcards, treat as substring
    search_pattern = pattern.strip()
    if "%" not in search_pattern:
        search_pattern = f"%{search_pattern}%"

    # Build node_id restriction if paths provided
    node_uuids: list[str] | None = None
    if paths:
        node_uuids = []
        for p in paths:
            node = await get_node_by_path(conn, p)
            if node:
                node_uuids.append(str(node["id"]))
        if not node_uuids:
            return {"matches": [], "total": 0}

    if node_uuids:
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
            node_uuids, search_pattern, limit,
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
            search_pattern, limit,
        )

    matches = [
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

    return {"matches": matches, "total": len(matches)}
