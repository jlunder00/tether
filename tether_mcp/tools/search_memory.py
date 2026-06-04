"""search_memory MCP tool — ILIKE search over user memory tables.

Searches user_memory (L2) and/or user_durable_memory (L3) by key and value.
Results are ranked by relevance: exact key match > key substring > value match.
"""
from __future__ import annotations

import asyncpg


async def execute_search_memory(
    conn: asyncpg.Connection,
    query: str,
    scope: str = "user",
    tier: str = "both",
    limit: int = 5,
) -> dict:
    """Search user memory entries by key or value.

    Args:
        conn:  asyncpg connection (user-scoped via RLS).
        query: Search string — matched against key (ILIKE) and value (ILIKE).
        scope: 'user' (default, kept for API compatibility).
        tier:  'l2' | 'both' → user_memory; 'l3' → user_durable_memory;
               'both' → searches both tables and merges.
        limit: Max results per tier (1-20).

    Returns:
        {results: [{key, value, score, tier}], total}
    """
    from db.pg_queries.memory import search_user_memory

    if not query or not query.strip():
        return {"error": "query_required"}

    if tier not in ("l2", "l3", "both"):
        return {"error": "invalid_tier", "valid_tiers": ["l2", "l3", "both"]}

    limit = min(max(1, limit), 20)
    q = query.strip()

    results: list[dict] = []

    if tier in ("l2", "both"):
        rows = await search_user_memory(conn, q, scope="user", limit=limit)
        for r in rows:
            results.append({**r, "tier": "l2"})

    if tier in ("l3", "both"):
        rows = await search_user_memory(conn, q, scope="user_durable", limit=limit)
        for r in rows:
            results.append({**r, "tier": "l3"})

    # When tier='both', re-sort merged results by score descending then key
    if tier == "both":
        results.sort(key=lambda x: (-x["score"], x["key"]))
        results = results[:limit]

    return {"results": results, "total": len(results)}
