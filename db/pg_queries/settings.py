"""Async Postgres queries — user_settings and links tables."""
from __future__ import annotations

import asyncpg


# ---------------------------------------------------------------------------
# user_settings
# ---------------------------------------------------------------------------


async def get_user_setting(conn: asyncpg.Connection, key: str) -> str | None:
    """Get a single user setting value for the current user, or None if not set."""
    row = await conn.fetchrow(
        """
        SELECT value FROM user_settings
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
          AND key = $1
        """,
        key,
    )
    return row["value"] if row else None


async def get_all_user_settings(conn: asyncpg.Connection) -> dict[str, str]:
    """Get all settings for the current user as a {key: value} dict."""
    rows = await conn.fetch(
        """
        SELECT key, value FROM user_settings
        WHERE user_id = current_setting('app.current_user_id', true)::uuid
        """
    )
    return {r["key"]: r["value"] for r in rows}


async def set_user_setting(conn: asyncpg.Connection, key: str, value: str) -> None:
    """Upsert a user setting for the current user."""
    await conn.execute(
        """
        INSERT INTO user_settings (user_id, key, value)
        VALUES (current_setting('app.current_user_id', true)::uuid, $1, $2)
        ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value
        """,
        key,
        value,
    )


# ---------------------------------------------------------------------------
# links
# ---------------------------------------------------------------------------


async def get_links(
    conn: asyncpg.Connection, parent_type: str, parent_id: str
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, parent_type, parent_id, url, label, category, created_at
        FROM links
        WHERE parent_type = $1
          AND parent_id = $2
          AND user_id = current_setting('app.current_user_id', true)::uuid
        ORDER BY id
        """,
        parent_type,
        parent_id,
    )
    return [dict(r) for r in rows]


async def create_link(
    conn: asyncpg.Connection,
    parent_type: str,
    parent_id: str,
    url: str,
    label: str | None = None,
    category: str = "other",
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO links (user_id, parent_type, parent_id, url, label, category)
        VALUES (current_setting('app.current_user_id', true)::uuid, $1, $2, $3, $4, $5)
        RETURNING id, parent_type, parent_id, url, label, category, created_at
        """,
        parent_type,
        parent_id,
        url,
        label,
        category,
    )
    return dict(row)


async def delete_link(conn: asyncpg.Connection, link_id: int) -> None:
    await conn.execute(
        """
        DELETE FROM links
        WHERE id = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        link_id,
    )
