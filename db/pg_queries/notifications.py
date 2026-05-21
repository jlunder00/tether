"""Async Postgres queries — notification_channels + routing preferences.

Covers the notification_channels table and the notification_routing key
within user_preferences. RLS on notification_channels enforces per-user
isolation; callers must have set app.current_user_id before invoking
these functions.
"""
from __future__ import annotations

import asyncpg


# ---------------------------------------------------------------------------
# notification_channels
# ---------------------------------------------------------------------------


async def get_notification_channels(
    conn: asyncpg.Connection,
    user_id: str,
    *,
    enabled_only: bool = True,
) -> list[dict]:
    """Return all notification channels for a user.

    Args:
        enabled_only: When True (default), return only enabled channels.
    """
    query = """
        SELECT
            id::text AS id,
            user_id::text AS user_id,
            channel_type,
            config,
            label,
            enabled,
            created_at
        FROM notification_channels
        WHERE user_id = $1::uuid
    """
    if enabled_only:
        query += " AND enabled = true"
    query += " ORDER BY created_at"

    rows = await conn.fetch(query, user_id)
    return [dict(r) for r in rows]


async def get_channels_by_type(
    conn: asyncpg.Connection,
    user_id: str,
    channel_type: str,
) -> list[dict]:
    """Return all enabled channels of a specific type for a user."""
    rows = await conn.fetch(
        """
        SELECT
            id::text AS id,
            channel_type,
            config,
            label,
            enabled
        FROM notification_channels
        WHERE user_id = $1::uuid
          AND channel_type = $2
          AND enabled = true
        ORDER BY created_at
        """,
        user_id,
        channel_type,
    )
    return [dict(r) for r in rows]


async def create_notification_channel(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    channel_type: str,
    config: dict,
    label: str | None = None,
    enabled: bool = True,
) -> str:
    """Insert a new notification_channels row. Returns the new UUID as a string."""
    row = await conn.fetchrow(
        """
        INSERT INTO notification_channels (user_id, channel_type, config, label, enabled)
        VALUES ($1::uuid, $2, $3, $4, $5)
        RETURNING id::text
        """,
        user_id,
        channel_type,
        config,
        label,
        enabled,
    )
    return row["id"]


async def upsert_channel_enabled(
    conn: asyncpg.Connection,
    channel_id: str,
    enabled: bool,
) -> None:
    """Enable or disable a notification channel."""
    await conn.execute(
        "UPDATE notification_channels SET enabled = $1 WHERE id = $2::uuid",
        enabled,
        channel_id,
    )


# ---------------------------------------------------------------------------
# Notification routing preferences (stored in user_preferences JSONB)
# ---------------------------------------------------------------------------

_ROUTING_PREF_KEY = "notification_routing"

_DEFAULT_ROUTING: dict = {
    "anchor_ping": {
        "mode": "thread_by_key",
        "key_template": "anchor:{anchor_id}:{date}",
        "priority": "important",
        "external": ["telegram"],
    },
    "task_followup": {
        "mode": "thread_by_key",
        "key_template": "anchor:{anchor_id}:{date}",
        "priority": "important",
        "external": ["telegram"],
    },
    "beacon": {
        "mode": "bot_decides",
        "priority": "normal",
        "external": ["web"],
    },
    "meeting_event": {
        "mode": "thread_by_key",
        "key_template": "meeting:{request_id}",
        "priority": "important",
        "external": ["telegram", "web"],
    },
    "scheduling_update": {
        "mode": "fixed",
        "priority": "normal",
        "external": ["web"],
    },
}


async def get_notification_routing(
    conn: asyncpg.Connection,
    user_id: str,
) -> dict | None:
    """Return the user's notification_routing preferences dict, or None if unset.

    The value is stored as JSON text in user_preferences with key='notification_routing'.
    """
    import json

    row = await conn.fetchrow(
        """
        SELECT value
        FROM user_preferences
        WHERE user_id = $1::uuid
          AND key = $2
        """,
        user_id,
        _ROUTING_PREF_KEY,
    )
    if row is None or row["value"] is None:
        return None
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return None


async def get_notification_routing_with_defaults(
    conn: asyncpg.Connection,
    user_id: str,
) -> dict:
    """Return the user's routing prefs, falling back to defaults for missing keys."""
    stored = await get_notification_routing(conn, user_id)
    if stored is None:
        return dict(_DEFAULT_ROUTING)
    return {**_DEFAULT_ROUTING, **stored}


async def set_notification_routing(
    conn: asyncpg.Connection,
    user_id: str,
    routing: dict,
) -> None:
    """Persist the notification_routing dict in user_preferences as JSON text."""
    import json

    await conn.execute(
        """
        INSERT INTO user_preferences (user_id, key, value)
        VALUES ($1::uuid, $2, $3)
        ON CONFLICT (user_id, key) DO UPDATE
            SET value = $3, updated_at = now()
        """,
        user_id,
        _ROUTING_PREF_KEY,
        json.dumps(routing),
    )
