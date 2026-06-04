"""search_context MCP tool — semantic search over context nodes (v1 stub).

v1: Returns empty results. Full implementation (pgvector or external embedding
service) deferred to v2 once the embedding pipeline is designed.

The tool signature is final — v2 will fill in the implementation without
changing the API. Callers can depend on the return shape now.
"""
from __future__ import annotations

import asyncpg


async def execute_search_context(
    conn: asyncpg.Connection,
    query: str,
    scope: str = "user",
    limit: int = 5,
) -> dict:
    """Semantic search over context nodes (v1 stub — always returns empty).

    Args:
        conn:  asyncpg connection (user-scoped via RLS).
        query: Natural language search query.
        scope: 'user' (all user nodes) or a node path prefix.
        limit: Max results (1-20).

    Returns:
        {results: [], total: 0, note: 'stub'}
    """
    return {
        "results": [],
        "total": 0,
        "note": "search_context is a v1 stub — semantic search not yet implemented",
    }
