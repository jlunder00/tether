"""grep_context MCP tool — text search (ILIKE) over node section bodies.

All SQL lives in db/pg_queries/sections.grep_sections().
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
        pattern: Search string. Plain text is auto-wrapped in % (substring match).
                 Use % explicitly for custom wildcard positioning.
        scope:   'user' (default) — search user's own nodes only (RLS enforced).
        paths:   Optional list of node paths to restrict search to their subtrees.
        limit:   Max results (default 20, max 100).

    Returns:
        {matches: [{node_id, node_name, section_type, section_name, snippet,
                    origin, visible_to_user}], total}
    """
    from db.pg_queries.sections import grep_sections
    from db.pg_queries.nodes import get_node_by_path

    if not pattern or not pattern.strip():
        return {"error": "pattern_required"}

    limit = min(limit, 100)

    # Normalize: wrap plain text in % wildcards for substring match
    search_pattern = pattern.strip()
    if "%" not in search_pattern:
        search_pattern = f"%{search_pattern}%"

    # Resolve path restrictions to node UUIDs
    node_ids: list[str] | None = None
    if paths:
        node_ids = []
        for p in paths:
            node = await get_node_by_path(conn, p)
            if node:
                node_ids.append(str(node["id"]))
        if not node_ids:
            return {"matches": [], "total": 0}

    matches = await grep_sections(conn, search_pattern, node_ids=node_ids, limit=limit)
    return {"matches": matches, "total": len(matches)}
