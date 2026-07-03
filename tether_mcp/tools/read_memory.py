"""read_memory MCP tool — read user_memory or user_durable_memory at a given M-level.

M-level semantics for memory (no descent gates — entries are atomic):
  M=1  key listing only
  M=2  key + ~50-char preview    (default — good for triage context)
  M=3  key + ~200-char truncated value
  M=4  key + full value

scope controls which table:
  'user'         → user_memory (L2 working memory)
  'user_durable' → user_durable_memory (L3 compacted patterns)

key: exact key lookup (returns at most one entry, full M=4 regardless of M param)
prefix: filter by key prefix (e.g., 'preferences/')
If neither key nor prefix is provided, returns all entries at the requested M.
"""
from __future__ import annotations

import asyncpg


async def execute_read_memory(
    conn: asyncpg.Connection,
    scope: str = "user",
    key: str | None = None,
    prefix: str | None = None,
    M: int = 2,
) -> dict:
    """Fetch user memory entries for the current RLS user.

    Args:
        conn:   asyncpg connection (user-scoped via RLS).
        scope:  'user' (L2) or 'user_durable' (L3).
        key:    Exact key for a single-entry lookup (returns full value, ignores M).
        prefix: Key prefix filter (e.g., 'preferences/').
        M:      Detail level — 1 (keys), 2 (preview), 3 (truncated), 4 (full).

    Returns:
        {scope, M, entries: [...]}
        For single-key lookup: {scope, entry: {...} | null}
    """
    from db.pg_queries.memory import (
        get_user_memory_entry,
        get_user_durable_memory_entry,
        list_user_memory,
        list_user_durable_memory,
    )

    if scope not in ("user", "user_durable"):
        return {"error": "invalid_scope", "valid_scopes": ["user", "user_durable"]}

    if M not in (1, 2, 3, 4):
        return {"error": "invalid_M", "valid_values": [1, 2, 3, 4]}

    if key is not None:
        # Single-entry lookup — always full value
        if scope == "user":
            entry = await get_user_memory_entry(conn, key)
        else:
            entry = await get_user_durable_memory_entry(conn, key)
        return {"scope": scope, "entry": entry}

    # List (with optional prefix)
    if scope == "user":
        entries = await list_user_memory(conn, prefix=prefix, M=M)
    else:
        entries = await list_user_durable_memory(conn, prefix=prefix, M=M)

    return {"scope": scope, "M": M, "entries": entries}
