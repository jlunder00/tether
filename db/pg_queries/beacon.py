"""Async Postgres queries — beacon_state table.

beacon_state: user_id UUID PRIMARY KEY, last_invoked_at TIMESTAMPTZ
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime

import asyncpg


async def record_beacon_invocation(
    conn: asyncpg.Connection, user_id: str
) -> None:
    """Upsert the current time as the last Beacon invocation for user_id."""
    await conn.execute(
        """
        INSERT INTO beacon_state (user_id, last_invoked_at)
        VALUES ($1, now())
        ON CONFLICT (user_id) DO UPDATE SET last_invoked_at = now()
        """,
        _uuid.UUID(user_id),
    )


async def get_last_invocation(
    conn: asyncpg.Connection, user_id: str
) -> datetime | None:
    """Return the last Beacon invocation timestamp for user_id, or None."""
    row = await conn.fetchrow(
        """
        SELECT last_invoked_at
        FROM beacon_state
        WHERE user_id = $1
        """,
        _uuid.UUID(user_id),
    )
    if not row or row["last_invoked_at"] is None:
        return None
    return row["last_invoked_at"]
