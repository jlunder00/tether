"""Async Postgres queries — conversation_history, orchestrator_conversation,
staging_mutations, and invocation_log tables."""
from __future__ import annotations

import asyncpg


# ---------------------------------------------------------------------------
# conversation_history
# ---------------------------------------------------------------------------


async def insert_conversation_turn(
    conn: asyncpg.Connection, role: str, body: str
) -> None:
    """Append one turn to conversation history. role is 'user' or 'assistant'."""
    await conn.execute(
        """
        INSERT INTO conversation_history (user_id, role, body)
        VALUES (current_setting('app.current_user_id', true)::uuid, $1, $2)
        """,
        role,
        body,
    )


async def get_recent_history(
    conn: asyncpg.Connection, n: int = 5
) -> list[dict]:
    """Return the last n exchange pairs (up to 2*n rows) in chronological order."""
    rows = await conn.fetch(
        """
        SELECT role, body, ts
        FROM conversation_history
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
        ORDER BY id DESC
        LIMIT $1
        """,
        n * 2,
    )
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# clear_session_state
# ---------------------------------------------------------------------------


async def clear_session_state(conn: asyncpg.Connection, session_id: str) -> None:
    """Delete all staging mutations, orchestrator conversation, and conversation
    history rows for a session."""
    await conn.execute(
        """
        DELETE FROM staging_mutations
        WHERE session_id = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        session_id,
    )
    await conn.execute(
        """
        DELETE FROM orchestrator_conversation
        WHERE session_id = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        session_id,
    )


# ---------------------------------------------------------------------------
# orchestrator_conversation
# ---------------------------------------------------------------------------


async def insert_orchestrator_turn(
    conn: asyncpg.Connection,
    session_id: str,
    role: str,
    body: str,
    round_num: int,
) -> None:
    await conn.execute(
        """
        INSERT INTO orchestrator_conversation (user_id, session_id, role, body, round_num)
        VALUES (current_setting('app.current_user_id', true)::uuid, $1, $2, $3, $4)
        """,
        session_id,
        role,
        body,
        round_num,
    )


async def get_orchestrator_conversation(
    conn: asyncpg.Connection, session_id: str
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT role, body, round_num, ts
        FROM orchestrator_conversation
        WHERE session_id = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        ORDER BY id
        """,
        session_id,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# staging_mutations
# ---------------------------------------------------------------------------


async def upsert_staging_mutation(
    conn: asyncpg.Connection,
    session_id: str,
    id: str,
    type: str,
    description: str,
    params_json: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO staging_mutations
            (id, user_id, session_id, type, description, params_json, created_at, updated_at)
        VALUES
            ($1, current_setting('app.current_user_id', true)::uuid, $2, $3, $4, $5, now(), now())
        ON CONFLICT (id, user_id) DO UPDATE SET
            description = EXCLUDED.description,
            params_json = EXCLUDED.params_json,
            updated_at  = EXCLUDED.updated_at
        """,
        id,
        session_id,
        type,
        description,
        params_json,
    )


async def get_staging_mutations(
    conn: asyncpg.Connection, session_id: str
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, session_id, type, description, params_json, created_at, updated_at
        FROM staging_mutations
        WHERE session_id = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        ORDER BY created_at
        """,
        session_id,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# invocation_log
# ---------------------------------------------------------------------------


async def log_stage(
    conn: asyncpg.Connection,
    session_id: str,
    stage: str,
    prompt: str,
    response: str,
    error: str | None = None,
) -> None:
    """Append one pipeline stage to the invocation log; prune to last 10 sessions."""
    await conn.execute(
        """
        INSERT INTO invocation_log (user_id, session_id, stage, prompt, response, error, ts)
        VALUES (current_setting('app.current_user_id', true)::uuid, $1, $2, $3, $4, $5, now())
        """,
        session_id,
        stage,
        prompt,
        response,
        error,
    )
    # Prune to last 10 sessions
    await conn.execute(
        """
        DELETE FROM invocation_log
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
          AND session_id NOT IN (
            SELECT session_id FROM (
                SELECT session_id, MAX(ts) AS latest
                FROM invocation_log
                WHERE user_id = current_setting('app.current_user_id', true)::uuid
                GROUP BY session_id
                ORDER BY latest DESC
                LIMIT 10
            ) sub
          )
        """
    )


async def get_invocation_log(
    conn: asyncpg.Connection, n: int = 5
) -> list[dict]:
    """Return all log entries for the last n sessions, oldest first."""
    rows = await conn.fetch(
        """
        SELECT id, session_id, stage, prompt, response, error, ts
        FROM invocation_log
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
          AND session_id IN (
            SELECT session_id FROM (
                SELECT session_id, MAX(ts) AS latest
                FROM invocation_log
                WHERE user_id = current_setting('app.current_user_id', true)::uuid
                GROUP BY session_id
                ORDER BY latest DESC
                LIMIT $1
            ) sub
          )
        ORDER BY id
        """,
        n,
    )
    return [dict(r) for r in rows]


async def get_last_bot_activity(conn: asyncpg.Connection) -> dict | None:
    """Return the most recent invocation_log entry for the current user."""
    row = await conn.fetchrow(
        """
        SELECT stage, response, error, ts
        FROM invocation_log
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
        ORDER BY id DESC
        LIMIT 1
        """
    )
    if not row:
        return None
    return {
        "stage": row["stage"],
        "response": row["response"][:200] if row["response"] else None,
        "error": row["error"],
        "ts": row["ts"],
    }
