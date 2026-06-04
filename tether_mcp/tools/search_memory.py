"""search_memory MCP tool — semantic search over user memory (v1 stub).

v1: Returns empty results. Full implementation deferred to v2 (pgvector or
external embedding service).

The tool signature is final — v2 fills in the implementation without API change.
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
    """Semantic search over user memory (v1 stub — always returns empty).

    Args:
        conn:  asyncpg connection (user-scoped via RLS).
        query: Natural language search query.
        scope: 'user' (default).
        tier:  'l2' | 'l3' | 'both' — which memory tier to search.
        limit: Max results (1-20).

    Returns:
        {results: [], total: 0, note: 'stub'}
    """
    return {
        "results": [],
        "total": 0,
        "note": "search_memory is a v1 stub — semantic search not yet implemented",
    }
