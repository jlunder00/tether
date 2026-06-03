"""Async Postgres queries — node_data_summary and node_read_log.

node_data_summary: M-level summarization cache per context_node.
  Populated by Beacon (Stream D summarization — NOT this module's concern).
  Read by MCP tools to serve M-level detail without loading all sections.
  Degrades gracefully when no rows exist (callers fall back to node_sections).

node_read_log: per-conversation read-credit tracking.
  Inserted by read_context / read_node_memory on every access.
  Consulted by write_node_memory for advisory read-before-write check.

All queries use RLS — callers must have set app.current_user_id.
"""
from __future__ import annotations

import uuid as _uuid

import asyncpg


# ─────────────────────────────────────────────────────────────────────────────
# node_data_summary
# ─────────────────────────────────────────────────────────────────────────────


async def get_node_summary(
    conn: asyncpg.Connection,
    node_id: str,
    level_ordinal: int,
) -> dict | None:
    """Return the summary row for (node_id, level_ordinal), or None if absent.

    Callers should degrade gracefully when None is returned:
    - For M < last: no summary cached yet (Beacon hasn't summarized)
    - For M = last: fall back to node_sections directly
    """
    row = await conn.fetchrow(
        """
        SELECT node_id::text, level_ordinal, value, abstract, source_checksum, generated_at
        FROM node_data_summary
        WHERE node_id = $1::uuid AND level_ordinal = $2
        """,
        _uuid.UUID(node_id), level_ordinal,
    )
    return dict(row) if row else None


async def list_node_summary_levels(
    conn: asyncpg.Connection,
    node_id: str,
) -> list[int]:
    """Return all available level_ordinal values for a node (sorted ascending).

    Useful for read_context to know which M-levels are cached vs. must fall back.
    """
    rows = await conn.fetch(
        """
        SELECT level_ordinal
        FROM node_data_summary
        WHERE node_id = $1::uuid
        ORDER BY level_ordinal
        """,
        _uuid.UUID(node_id),
    )
    return [r["level_ordinal"] for r in rows]


async def upsert_node_summary(
    conn: asyncpg.Connection,
    node_id: str,
    level_ordinal: int,
    value: dict,
    source_checksum: str,
    *,
    abstract: str | None = None,
) -> dict:
    """Upsert a summary row. Called by Beacon summarization (Stream D).

    Not called by read tools — this is write-only from the summarizer side.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO node_data_summary
            (user_id, node_id, level_ordinal, value, abstract, source_checksum, generated_at)
        VALUES (
            current_setting('app.current_user_id', true)::uuid,
            $1::uuid, $2, $3::jsonb, $4, $5, now()
        )
        ON CONFLICT (node_id, level_ordinal) DO UPDATE
            SET value           = EXCLUDED.value,
                abstract        = EXCLUDED.abstract,
                source_checksum = EXCLUDED.source_checksum,
                generated_at    = now()
        RETURNING node_id::text, level_ordinal, abstract, source_checksum, generated_at
        """,
        _uuid.UUID(node_id), level_ordinal, value, abstract, source_checksum,
    )
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# node_read_log
# ─────────────────────────────────────────────────────────────────────────────


async def log_node_read(
    conn: asyncpg.Connection,
    node_id: str,
    level_ordinal: int,
    *,
    conversation_id: str | None = None,
    title: str | None = None,
) -> None:
    """Record that the current user read node_id at level_ordinal in this conversation.

    Called by read_context and read_node_memory on every access.
    conversation_id may be None for admin/debug calls without conversation context.
    """
    conv_uuid = _uuid.UUID(conversation_id) if conversation_id else None
    await conn.execute(
        """
        INSERT INTO node_read_log (user_id, conversation_id, node_id, level_ordinal, title)
        VALUES (
            current_setting('app.current_user_id', true)::uuid,
            $1, $2::uuid, $3, $4
        )
        """,
        conv_uuid, _uuid.UUID(node_id), level_ordinal, title,
    )


async def has_read_node_in_conversation(
    conn: asyncpg.Connection,
    node_id: str,
    conversation_id: str,
) -> bool:
    """Return True if any read of node_id was logged for this conversation.

    Used by write_node_memory advisory read-before-write check:
      v1: log WARNING if False but allow the write
      v2: hard block if False once Stream C callers always provide conversation_id
    """
    count = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM node_read_log
        WHERE user_id         = current_setting('app.current_user_id', true)::uuid
          AND conversation_id = $1::uuid
          AND node_id         = $2::uuid
        """,
        _uuid.UUID(conversation_id), _uuid.UUID(node_id),
    )
    return (count or 0) > 0


async def get_conversation_reads(
    conn: asyncpg.Connection,
    conversation_id: str,
) -> list[dict]:
    """Return all node read credits for a conversation (newest first).

    Used for diagnostics and advisory enforcement reports.
    """
    rows = await conn.fetch(
        """
        SELECT node_id::text, level_ordinal, title, read_at
        FROM node_read_log
        WHERE user_id         = current_setting('app.current_user_id', true)::uuid
          AND conversation_id = $1::uuid
        ORDER BY read_at DESC
        """,
        _uuid.UUID(conversation_id),
    )
    return [dict(r) for r in rows]
