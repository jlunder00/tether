"""Async Postgres queries — conversations table.

Covers CRUD for the conversations model introduced in the notification
system overhaul (Phase B). RLS on the conversations table enforces
per-user isolation; callers must have set app.current_user_id before
invoking these functions.
"""
from __future__ import annotations

import asyncpg


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_conversation(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    name: str,
    notification_type: str,
    conversation_type: str = "interactive",
    priority: str = "normal",
    context_node_id: str | None = None,
    thread_key: str | None = None,
    is_system: bool = False,
) -> str:
    """Insert a new conversation row. Returns the new UUID as a string."""
    row = await conn.fetchrow(
        """
        INSERT INTO conversations
            (user_id, name, type, priority, context_node_id, thread_key, is_system)
        VALUES
            ($1::uuid, $2, $3, $4, $5::uuid, $6, $7)
        RETURNING id::text
        """,
        user_id,
        name,
        conversation_type,
        priority,
        context_node_id,
        thread_key,
        is_system,
    )
    return row["id"]


async def get_or_create_by_thread_key(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    thread_key: str,
    name: str,
    notification_type: str,
    context_node_id: str | None = None,
    priority: str = "normal",
) -> str:
    """Return an existing open conversation matching (user_id, thread_key),
    or create a new one. Returns the conversation UUID as a string.

    Uses INSERT ... ON CONFLICT DO NOTHING + a follow-up SELECT so the
    operation is safe under concurrent callers (the partial unique index
    on (user_id, thread_key) WHERE thread_key IS NOT NULL guarantees at-most-one).
    """
    # Try to insert; ignore if the (user_id, thread_key) pair already exists.
    await conn.execute(
        """
        INSERT INTO conversations
            (user_id, name, type, priority, context_node_id, thread_key)
        VALUES
            ($1::uuid, $2, 'interactive', $3, $4::uuid, $5)
        ON CONFLICT DO NOTHING
        """,
        user_id,
        name,
        priority,
        context_node_id,
        thread_key,
    )

    row = await conn.fetchrow(
        """
        SELECT id::text
        FROM conversations
        WHERE user_id = $1::uuid
          AND thread_key = $2
          AND state = 'open'
        LIMIT 1
        """,
        user_id,
        thread_key,
    )
    return row["id"]


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_conversation(
    conn: asyncpg.Connection,
    conversation_id: str,
) -> dict | None:
    """Fetch a conversation by id. Returns None if not found."""
    row = await conn.fetchrow(
        """
        SELECT
            id::text AS id,
            user_id::text AS user_id,
            name,
            type,
            priority,
            state,
            context_node_id::text AS context_node_id,
            thread_key,
            is_system,
            created_at,
            last_message_at
        FROM conversations
        WHERE id = $1::uuid
        """,
        conversation_id,
    )
    return dict(row) if row else None


async def get_open_conversation_by_thread_key(
    conn: asyncpg.Connection,
    user_id: str,
    thread_key: str,
) -> dict | None:
    """Return the open conversation matching (user_id, thread_key), or None."""
    row = await conn.fetchrow(
        """
        SELECT id::text AS id, name, priority, context_node_id::text AS context_node_id
        FROM conversations
        WHERE user_id = $1::uuid
          AND thread_key = $2
          AND state = 'open'
        LIMIT 1
        """,
        user_id,
        thread_key,
    )
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def touch_conversation(
    conn: asyncpg.Connection,
    conversation_id: str,
) -> None:
    """Update last_message_at to now() for the given conversation."""
    await conn.execute(
        """
        UPDATE conversations
        SET last_message_at = now()
        WHERE id = $1::uuid
        """,
        conversation_id,
    )


async def update_conversation(
    conn: asyncpg.Connection,
    conversation_id: str,
    *,
    name: str | None = None,
    priority: str | None = None,
    context_node_id: str | None = None,
    state: str | None = None,
) -> None:
    """Patch mutable fields on a conversation. Only provided fields are updated."""
    if name is not None:
        await conn.execute(
            "UPDATE conversations SET name = $1 WHERE id = $2::uuid",
            name,
            conversation_id,
        )
    if priority is not None:
        await conn.execute(
            "UPDATE conversations SET priority = $1 WHERE id = $2::uuid",
            priority,
            conversation_id,
        )
    if context_node_id is not None:
        await conn.execute(
            "UPDATE conversations SET context_node_id = $1::uuid WHERE id = $2::uuid",
            context_node_id,
            conversation_id,
        )
    if state is not None:
        await conn.execute(
            "UPDATE conversations SET state = $1 WHERE id = $2::uuid",
            state,
            conversation_id,
        )
