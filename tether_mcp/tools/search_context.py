"""search_context MCP tool — full-text search over context node sections.

Uses Postgres tsvector (trigger-maintained search_vector column with GIN index)
to rank results by relevance. Distinct from grep_context which uses ILIKE for
substring matching; this tool uses plainto_tsquery for natural-language FTS.
"""
from __future__ import annotations

import asyncpg


async def execute_search_context(
    conn: asyncpg.Connection,
    query: str,
    scope: str = "user",
    paths: list[str] | None = None,
    limit: int = 5,
) -> dict:
    """Full-text search over node section bodies.

    Args:
        conn:  asyncpg connection (user-scoped via RLS).
        query: Natural language search query (passed to plainto_tsquery).
        scope: 'user' — RLS-enforced search over user's own nodes only.
        paths: Optional list of node paths to restrict search to their subtrees.
        limit: Max results (1-20).

    Returns:
        {results: [{node_id, node_title, section_title, snippet, score}], total}
    """
    from db.pg_queries.sections import search_sections_fts
    from db.pg_queries.nodes import get_node_by_path

    if not query or not query.strip():
        return {"error": "query_required"}

    limit = min(max(1, limit), 20)

    # Resolve path restrictions to node UUIDs
    node_ids: list[str] | None = None
    if paths:
        node_ids = []
        for p in paths:
            node = await get_node_by_path(conn, p)
            if node:
                node_ids.append(str(node["id"]))
        if not node_ids:
            return {"results": [], "total": 0}

    rows = await search_sections_fts(
        conn, query.strip(), node_ids=node_ids, limit=limit
    )

    results = [
        {
            "node_id": r["node_id"],
            "node_title": r["node_name"],
            "section_title": r["section_name"],
            "snippet": r["snippet"],
            "score": r["score"],
        }
        for r in rows
    ]
    return {"results": results, "total": len(results)}
