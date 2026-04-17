"""Async Postgres auth queries — users, OAuth, invite tokens, Telegram.

Auth tables have NO Row-Level Security. Callers must use get_conn(pool) with
no user_id arg so the connection is unscoped.
"""
from __future__ import annotations
import uuid as _uuid
from datetime import datetime, timezone

import asyncpg


def _row(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    return {k: str(v) if isinstance(v, _uuid.UUID) else v for k, v in dict(row).items()}


def _rows(rows) -> list[dict]:
    return [_row(r) for r in rows]


async def create_user(
    conn: asyncpg.Connection,
    username: str,
    email: str,
    password_hash: str | None = None,
    is_admin: bool = False,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO users (username, email, password_hash, is_admin)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        username, email, password_hash, is_admin,
    )
    return _row(row)


async def get_user_by_id(conn: asyncpg.Connection, user_id: str) -> dict | None:
    row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", _uuid.UUID(user_id))
    return _row(row)


async def get_user_by_email(conn: asyncpg.Connection, email: str) -> dict | None:
    row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
    return _row(row)


async def get_user_by_username(conn: asyncpg.Connection, username: str) -> dict | None:
    row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
    return _row(row)


async def get_user_count(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT COUNT(*) FROM users")


async def create_oauth_connection(
    conn: asyncpg.Connection,
    user_id: str,
    provider: str,
    provider_user_id: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO oauth_connections
            (user_id, provider, provider_user_id, access_token, refresh_token)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (provider, provider_user_id) DO NOTHING
        """,
        _uuid.UUID(user_id), provider, provider_user_id, access_token, refresh_token,
    )


async def get_user_by_oauth(
    conn: asyncpg.Connection, provider: str, provider_user_id: str
) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT u.*
        FROM users u
        JOIN oauth_connections o ON o.user_id = u.id
        WHERE o.provider = $1 AND o.provider_user_id = $2
        """,
        provider, provider_user_id,
    )
    return _row(row)


async def create_invite_token(
    conn: asyncpg.Connection, created_by: str, expires_at: datetime
) -> str:
    token = str(_uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO invite_tokens (token, created_by, expires_at)
        VALUES ($1, $2, $3)
        """,
        token, _uuid.UUID(created_by), expires_at,
    )
    return token


async def use_invite_token(conn: asyncpg.Connection, token: str, user_id: str) -> bool:
    row = await conn.fetchrow(
        "SELECT used_by, expires_at FROM invite_tokens WHERE token = $1", token
    )
    if row is None:
        return False
    if row["used_by"] is not None:
        return False
    if row["expires_at"] < datetime.now(timezone.utc):
        return False
    await conn.execute(
        "UPDATE invite_tokens SET used_by = $1 WHERE token = $2",
        _uuid.UUID(user_id), token,
    )
    return True


async def get_invite_tokens(conn: asyncpg.Connection, created_by: str) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM invite_tokens WHERE created_by = $1 ORDER BY created_at",
        _uuid.UUID(created_by),
    )
    return _rows(rows)


async def set_telegram_connection(
    conn: asyncpg.Connection, user_id: str, chat_id: str
) -> None:
    await conn.execute(
        """
        INSERT INTO telegram_connections (user_id, telegram_chat_id)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET telegram_chat_id = EXCLUDED.telegram_chat_id
        """,
        _uuid.UUID(user_id), chat_id,
    )


async def get_user_by_telegram_chat_id(
    conn: asyncpg.Connection, chat_id: str
) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT u.*
        FROM users u
        JOIN telegram_connections t ON t.user_id = u.id
        WHERE t.telegram_chat_id = $1
        """,
        chat_id,
    )
    return _row(row)


async def store_link_code(conn: asyncpg.Connection, code: str, chat_id: str) -> None:
    await conn.execute(
        """
        INSERT INTO telegram_link_codes (code, telegram_chat_id)
        VALUES ($1, $2)
        ON CONFLICT (code) DO UPDATE SET telegram_chat_id = EXCLUDED.telegram_chat_id
        """,
        code, chat_id,
    )


async def verify_and_consume_link_code(
    conn: asyncpg.Connection, code: str
) -> str | None:
    """Verify code is not expired (< 5 min old), delete it, return chat_id or None."""
    row = await conn.fetchrow(
        """
        DELETE FROM telegram_link_codes
        WHERE code = $1
          AND created_at > now() - interval '5 minutes'
        RETURNING telegram_chat_id
        """,
        code,
    )
    return row["telegram_chat_id"] if row else None
