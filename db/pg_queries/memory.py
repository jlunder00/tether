"""Async Postgres queries — user_memory, user_durable_memory, pending_memory_writes.

user_memory: L2 working memory (user facts, patterns, preferences).
  Written by Beacon; read by interactive 2.5 agents at session start (full M=4).
  Keyed by hierarchical convention: 'preferences/morning_routine', 'facts/work/role', etc.

user_durable_memory: L3 compacted long-term user patterns.
  Written by Beacon compaction only (monthly+). More stable than L2.

pending_memory_writes: proposals from MCP tool propose_user_memory_write().
  Beacon post-conversation evaluator reviews and commits or discards.

All three tables carry RLS — callers must have set app.current_user_id before
invoking these functions.
"""
from __future__ import annotations

import asyncpg


# ─────────────────────────────────────────────────────────────────────────────
# user_memory (L2)
# ─────────────────────────────────────────────────────────────────────────────


async def list_user_memory(
    conn: asyncpg.Connection,
    *,
    prefix: str | None = None,
    M: int = 2,
) -> list[dict]:
    """Return user_memory entries for the current RLS user.

    M controls how much data is returned per entry:
      M=1  key only
      M=2  key + ~50-char preview of value
      M=3  key + ~200-char truncated value
      M=4  key + full value

    Optional prefix filters by key prefix (e.g., 'preferences/').
    """
    if M == 1:
        select = "key"
    elif M == 2:
        select = "key, left(value, 50) AS value"
    elif M == 3:
        select = "key, left(value, 200) AS value"
    else:
        select = "key, value, updated_at, last_read_at"

    if prefix:
        rows = await conn.fetch(
            f"SELECT {select} FROM user_memory WHERE key LIKE $1 || '%' ORDER BY key",
            prefix,
        )
    else:
        rows = await conn.fetch(
            f"SELECT {select} FROM user_memory ORDER BY key",
        )
    return [dict(r) for r in rows]


async def get_user_memory_entry(
    conn: asyncpg.Connection,
    key: str,
) -> dict | None:
    """Fetch a single user_memory entry by exact key.

    Updates last_read_at as a side effect (tracks when Beacon last accessed it).
    """
    row = await conn.fetchrow(
        """
        UPDATE user_memory
           SET last_read_at = now()
         WHERE user_id = current_setting('app.current_user_id', true)::uuid
           AND key = $1
        RETURNING key, value, updated_at, last_read_at
        """,
        key,
    )
    return dict(row) if row else None


async def upsert_user_memory(
    conn: asyncpg.Connection,
    key: str,
    value: str,
) -> dict:
    """Write a user_memory entry (insert or update). Returns the final row."""
    row = await conn.fetchrow(
        """
        INSERT INTO user_memory (user_id, key, value, updated_at)
        VALUES (current_setting('app.current_user_id', true)::uuid, $1, $2, now())
        ON CONFLICT (user_id, key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = now()
        RETURNING key, value, updated_at
        """,
        key, value,
    )
    return dict(row)


async def delete_user_memory(
    conn: asyncpg.Connection,
    key: str,
) -> bool:
    """Delete a user_memory entry. Returns True if a row was deleted."""
    result = await conn.execute(
        """
        DELETE FROM user_memory
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
          AND key = $1
        """,
        key,
    )
    return result.split()[-1] != "0"


# ─────────────────────────────────────────────────────────────────────────────
# user_durable_memory (L3)
# ─────────────────────────────────────────────────────────────────────────────


async def list_user_durable_memory(
    conn: asyncpg.Connection,
    *,
    prefix: str | None = None,
    M: int = 2,
) -> list[dict]:
    """Return user_durable_memory entries for the current RLS user.

    Same M-level semantics as list_user_memory.
    """
    if M == 1:
        select = "key"
    elif M == 2:
        select = "key, left(value, 50) AS value"
    elif M == 3:
        select = "key, left(value, 200) AS value"
    else:
        select = "key, value, source, confidence, created_at, updated_at"

    if prefix:
        rows = await conn.fetch(
            f"SELECT {select} FROM user_durable_memory WHERE key LIKE $1 || '%' ORDER BY key",
            prefix,
        )
    else:
        rows = await conn.fetch(
            f"SELECT {select} FROM user_durable_memory ORDER BY key",
        )
    return [dict(r) for r in rows]


async def get_user_durable_memory_entry(
    conn: asyncpg.Connection,
    key: str,
) -> dict | None:
    """Fetch a single user_durable_memory entry by exact key (full data)."""
    row = await conn.fetchrow(
        """
        SELECT key, value, source, evidence, confidence, created_at, updated_at
        FROM user_durable_memory
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
          AND key = $1
        """,
        key,
    )
    return dict(row) if row else None


async def upsert_user_durable_memory(
    conn: asyncpg.Connection,
    key: str,
    value: str,
    source: str,
    *,
    evidence: dict | None = None,
    confidence: str = "medium",
) -> dict:
    """Write a user_durable_memory entry (insert or update). Returns the final row."""
    row = await conn.fetchrow(
        """
        INSERT INTO user_durable_memory (user_id, key, value, source, evidence, confidence, updated_at)
        VALUES (
            current_setting('app.current_user_id', true)::uuid,
            $1, $2, $3, $4, $5, now()
        )
        ON CONFLICT (user_id, key) DO UPDATE
            SET value      = EXCLUDED.value,
                source     = EXCLUDED.source,
                evidence   = EXCLUDED.evidence,
                confidence = EXCLUDED.confidence,
                updated_at = now()
        RETURNING key, value, source, confidence, updated_at
        """,
        key, value, source, evidence, confidence,
    )
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# pending_memory_writes
# ─────────────────────────────────────────────────────────────────────────────


async def insert_pending_memory_write(
    conn: asyncpg.Connection,
    key: str,
    value: str,
    reason: str,
    *,
    conversation_id: str | None = None,
) -> str:
    """Insert a pending_memory_write proposal. Returns the new UUID."""
    import uuid as _uuid
    conv_uuid = _uuid.UUID(conversation_id) if conversation_id else None
    row = await conn.fetchrow(
        """
        INSERT INTO pending_memory_writes (user_id, conversation_id, key, value, reason)
        VALUES (
            current_setting('app.current_user_id', true)::uuid,
            $1, $2, $3, $4
        )
        RETURNING id::text
        """,
        conv_uuid, key, value, reason,
    )
    return row["id"]


async def get_pending_memory_write(
    conn: asyncpg.Connection,
    proposal_id: str,
) -> dict | None:
    """Fetch a single pending_memory_write by ID."""
    import uuid as _uuid
    row = await conn.fetchrow(
        """
        SELECT id::text, key, value, reason, status, conversation_id::text, created_at, reviewed_at
        FROM pending_memory_writes
        WHERE id = $1::uuid
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        _uuid.UUID(proposal_id),
    )
    return dict(row) if row else None


async def list_pending_memory_writes(
    conn: asyncpg.Connection,
    *,
    status: str = "pending",
) -> list[dict]:
    """Return pending_memory_write proposals with the given status."""
    rows = await conn.fetch(
        """
        SELECT id::text, key, value, reason, status, conversation_id::text, created_at
        FROM pending_memory_writes
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
          AND status = $1
        ORDER BY created_at DESC
        """,
        status,
    )
    return [dict(r) for r in rows]


async def review_pending_memory_write(
    conn: asyncpg.Connection,
    proposal_id: str,
    new_status: str,
) -> bool:
    """Mark a proposal as 'accepted' or 'rejected'. Returns True if found."""
    import uuid as _uuid
    result = await conn.execute(
        """
        UPDATE pending_memory_writes
           SET status = $1, reviewed_at = now()
         WHERE id = $2::uuid
           AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        new_status, _uuid.UUID(proposal_id),
    )
    return result.split()[-1] != "0"
