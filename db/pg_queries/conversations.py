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


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


async def list_conversations(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    state: str | None = None,
    context_node_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return conversations for the given user, newest first.

    LEFT JOINs context_nodes so that folder_name is included in each row.
    Filters explicitly by user_id as defense-in-depth alongside RLS.
    """
    # $1 = limit, $2 = offset, $3 = user_id; optional filters appended as $4, $5...
    params: list = [limit, offset, user_id]
    conditions: list[str] = ["c.user_id = $3::uuid"]

    if state is not None:
        params.append(state)
        conditions.append(f"c.state = ${len(params)}")
    if context_node_id is not None:
        params.append(context_node_id)
        conditions.append(f"c.context_node_id = ${len(params)}::uuid")

    where = f"WHERE {' AND '.join(conditions)}"

    rows = await conn.fetch(
        f"""
        SELECT
            c.id::text        AS id,
            c.user_id::text   AS user_id,
            c.name,
            c.type,
            c.priority,
            c.state,
            c.context_node_id::text AS context_node_id,
            cn.name           AS folder_name,
            c.thread_key,
            c.is_system,
            c.created_at,
            c.last_message_at
        FROM conversations c
        LEFT JOIN context_nodes cn ON cn.id = c.context_node_id
        {where}
        ORDER BY c.last_message_at DESC NULLS LAST, c.created_at DESC
        LIMIT $1 OFFSET $2
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def list_conversation_messages(
    conn: asyncpg.Connection,
    conversation_id: str,
    *,
    limit: int = 50,
    before_id: str | None = None,
) -> dict:
    """Return messages for a conversation, newest first, with cursor pagination.

    Uses `before_id` cursor: returns rows with id < before_id so callers can
    paginate backwards through history. Returns {"messages": [...], "has_more": bool}.

    Note: `before_id` is an integer-typed primary key on conversation_history —
    this cursor approach is stable under concurrent inserts, unlike offset-based
    pagination. See PR description for rationale.
    """
    # Fetch limit+1 to determine has_more without a separate COUNT query.
    fetch_limit = limit + 1
    params: list = [conversation_id, fetch_limit]

    before_clause = ""
    if before_id is not None:
        params.append(int(before_id))
        before_clause = f"AND ch.id < ${len(params)}"

    rows = await conn.fetch(
        f"""
        SELECT
            ch.id::text           AS id,
            ch.role,
            ch.body,
            ch.conversation_id::text AS conversation_id,
            ch.ts                 AS created_at,
            ch.source,
            ch.channel
        FROM conversation_history ch
        WHERE ch.conversation_id = $1::uuid
          {before_clause}
        ORDER BY ch.id DESC
        LIMIT $2
        """,
        *params,
    )

    has_more = len(rows) > limit
    messages = [dict(r) for r in rows[:limit]]
    return {"messages": messages, "has_more": has_more}


async def list_conversations_index(
    conn: asyncpg.Connection,
    *,
    user_id: str,
) -> list[dict]:
    """Return a lightweight index of all conversations for the given user.

    Returns [{id, title, parent_context_node_id, state, priority, updated_at, message_count}].
    One query — no per-row N+1. Message bodies and full detail are excluded.
    Used by the frontend to populate conversation trees quickly.

    state and priority are included so the frontend can render pending badges
    and priority dots on first paint without a follow-up upgrade call.
    """
    rows = await conn.fetch(
        """
        SELECT
            c.id::text                       AS id,
            c.name                           AS title,
            c.context_node_id::text          AS parent_context_node_id,
            c.state,
            c.priority,
            COALESCE(c.last_message_at, c.created_at) AS updated_at,
            COUNT(ch.id)::int                AS message_count
        FROM conversations c
        LEFT JOIN conversation_history ch ON ch.conversation_id = c.id
        WHERE c.user_id = $1::uuid
        GROUP BY c.id, c.name, c.context_node_id, c.state, c.priority,
                 c.last_message_at, c.created_at
        ORDER BY COALESCE(c.last_message_at, c.created_at) DESC
        """,
        user_id,
    )
    return [dict(r) for r in rows]
