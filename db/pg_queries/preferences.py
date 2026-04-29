"""Async Postgres queries — user_preferences table."""
from __future__ import annotations
import asyncpg


async def upsert_user_preference(conn: asyncpg.Connection, user_id: str, key: str, value: str) -> None:
    await conn.execute(
        """INSERT INTO user_preferences (user_id, key, value)
           VALUES ($1::uuid, $2, $3)
           ON CONFLICT (user_id, key) DO UPDATE SET value = $3, updated_at = now()""",
        user_id, key, value,
    )


async def get_user_preferences(conn: asyncpg.Connection, user_id: str) -> dict[str, str]:
    rows = await conn.fetch(
        "SELECT key, value FROM user_preferences WHERE user_id = $1::uuid", user_id
    )
    return {r["key"]: r["value"] for r in rows}
