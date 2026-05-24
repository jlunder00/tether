"""Async Postgres queries — session_notes table.

session_notes: user_id UUID PRIMARY KEY, content TEXT, updated_at TIMESTAMPTZ

One row per user — a singleton accumulator for bot session summaries.
Callers own the append/rewrite logic; this layer is a plain get/upsert pair.
RLS ensures each connection can only see its own row.
"""
from __future__ import annotations

import asyncpg


async def get_session_notes(conn: asyncpg.Connection) -> str | None:
    """Return the session notes content for the current RLS user.

    Returns None when no row exists or when content is empty/whitespace-only.
    The caller can treat None as "no notes yet" and fall back to a template.
    """
    row = await conn.fetchrow(
        """
        SELECT content
        FROM session_notes
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
        """
    )
    if not row:
        return None
    content = row["content"]
    return content if content and content.strip() else None


async def upsert_session_notes(conn: asyncpg.Connection, content: str) -> None:
    """Write session notes for the current RLS user (insert or replace).

    On first call: inserts a new row.
    On subsequent calls: replaces content and refreshes updated_at.
    Empty string is a valid reset value (get_session_notes returns None for it).
    """
    await conn.execute(
        """
        INSERT INTO session_notes (user_id, content, updated_at)
        VALUES (current_setting('app.current_user_id', true)::uuid, $1, now())
        ON CONFLICT (user_id) DO UPDATE
            SET content    = EXCLUDED.content,
                updated_at = now()
        """,
        content,
    )
