"""Async Postgres queries — sessions table."""
from __future__ import annotations

import uuid as _uuid

import asyncpg

_VALID_SESSION_STATES = {"active", "waiting_user", "closed"}


async def create_session(
    conn: asyncpg.Connection, chat_id: str, max_turns: int = 10
) -> str:
    """Create a new session, closing any existing active session for this chat.
    Returns the new session id."""
    sid = str(_uuid.uuid4())
    # Close any existing active/waiting sessions for this chat
    await conn.execute(
        """
        UPDATE sessions
        SET state = 'closed'
        WHERE chat_id = $1
          AND state = ANY($2)
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        chat_id,
        ["active", "waiting_user"],
    )
    await conn.execute(
        """
        INSERT INTO sessions (id, user_id, chat_id, state, max_turns)
        VALUES ($1, current_setting('app.current_user_id', true)::uuid, $2, 'active', $3)
        """,
        sid,
        chat_id,
        max_turns,
    )
    return sid


async def get_active_session(
    conn: asyncpg.Connection, chat_id: str
) -> dict | None:
    """Get the active or waiting session for a chat, or None."""
    row = await conn.fetchrow(
        """
        SELECT *
        FROM sessions
        WHERE chat_id = $1
          AND state = ANY($2)
          AND user_id = current_setting('app.current_user_id', true)::uuid
        ORDER BY created_at DESC
        LIMIT 1
        """,
        chat_id,
        ["active", "waiting_user"],
    )
    if not row:
        return None
    d = dict(row)
    if d.get("id") and hasattr(d["id"], "hex"):
        d["id"] = str(d["id"])
    if d.get("user_id") and hasattr(d["user_id"], "hex"):
        d["user_id"] = str(d["user_id"])
    return d


async def update_session_state(
    conn: asyncpg.Connection, session_id: str, state: str
) -> None:
    """Update session state. Must be one of: active, waiting_user, closed."""
    if state not in _VALID_SESSION_STATES:
        raise ValueError(
            f"Invalid session state: {state!r}. Must be one of {_VALID_SESSION_STATES}"
        )
    await conn.execute(
        """
        UPDATE sessions
        SET state = $1, last_activity = now()
        WHERE id = $2
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        state,
        session_id,
    )


async def update_session_activity(
    conn: asyncpg.Connection, session_id: str, turn_count: int
) -> None:
    await conn.execute(
        """
        UPDATE sessions
        SET turn_count = $1, last_activity = now()
        WHERE id = $2
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        turn_count,
        session_id,
    )


async def close_session(
    conn: asyncpg.Connection, session_id: str, summary: str | None = None
) -> None:
    await conn.execute(
        """
        UPDATE sessions
        SET state = 'closed', summary = $1, last_activity = now()
        WHERE id = $2
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        summary,
        session_id,
    )


async def get_stale_sessions(
    conn: asyncpg.Connection, timeout_minutes: int = 15
) -> list[dict]:
    """Find sessions idle longer than timeout_minutes for the current user."""
    rows = await conn.fetch(
        """
        SELECT *
        FROM sessions
        WHERE state = ANY($1)
          AND last_activity < now() - ($2 * interval '1 minute')
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        ["active", "waiting_user"],
        timeout_minutes,
    )
    result = []
    for row in rows:
        d = dict(row)
        if d.get("id") and hasattr(d["id"], "hex"):
            d["id"] = str(d["id"])
        if d.get("user_id") and hasattr(d["user_id"], "hex"):
            d["user_id"] = str(d["user_id"])
        result.append(d)
    return result
