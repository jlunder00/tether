"""Async Postgres queries — user_integrations + integration_sync_state."""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

import asyncpg


def _row(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, _uuid.UUID):
            d[k] = str(v)
    return d


async def get_integration(
    conn: asyncpg.Connection,
    user_id: str,
    provider: str,
) -> dict | None:
    row = await conn.fetchrow(
        "SELECT * FROM user_integrations WHERE user_id = $1 AND provider = $2",
        user_id, provider,
    )
    return _row(row)


async def upsert_integration(
    conn: asyncpg.Connection,
    user_id: str,
    provider: str,
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    token_expiry: datetime | None = None,
    scopes: list[str] | None = None,
    metadata: dict | None = None,
    enabled: bool = True,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO user_integrations
            (user_id, provider, access_token, refresh_token, token_expiry,
             scopes, metadata, enabled)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (user_id, provider) DO UPDATE SET
            access_token  = COALESCE(EXCLUDED.access_token,  user_integrations.access_token),
            refresh_token = COALESCE(EXCLUDED.refresh_token, user_integrations.refresh_token),
            token_expiry  = COALESCE(EXCLUDED.token_expiry,  user_integrations.token_expiry),
            scopes        = COALESCE(EXCLUDED.scopes,        user_integrations.scopes),
            metadata      = COALESCE(EXCLUDED.metadata,      user_integrations.metadata),
            enabled       = EXCLUDED.enabled
        RETURNING *
        """,
        user_id, provider, access_token, refresh_token, token_expiry,
        scopes, metadata, enabled,
    )
    return _row(row)


async def delete_integration(
    conn: asyncpg.Connection,
    user_id: str,
    provider: str,
) -> bool:
    result = await conn.execute(
        "DELETE FROM user_integrations WHERE user_id = $1 AND provider = $2",
        user_id, provider,
    )
    return result == "DELETE 1"


async def get_sync_state(
    conn: asyncpg.Connection,
    integration_id: str,
    calendar_id: str,
) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT * FROM integration_sync_state
        WHERE integration_id = $1 AND calendar_id = $2
        """,
        _uuid.UUID(integration_id), calendar_id,
    )
    return _row(row)


async def upsert_sync_state(
    conn: asyncpg.Connection,
    integration_id: str,
    calendar_id: str,
    *,
    sync_cursor: str | None = None,
    watch_channel_id: str | None = None,
    watch_expiry: datetime | None = None,
    watch_resource_id: str | None = None,
) -> dict:
    row = await conn.fetchrow(
        """
        INSERT INTO integration_sync_state
            (integration_id, calendar_id, sync_cursor,
             watch_channel_id, watch_expiry, watch_resource_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (integration_id, calendar_id) DO UPDATE SET
            sync_cursor       = EXCLUDED.sync_cursor,
            watch_channel_id  = COALESCE(EXCLUDED.watch_channel_id,  integration_sync_state.watch_channel_id),
            watch_expiry      = COALESCE(EXCLUDED.watch_expiry,       integration_sync_state.watch_expiry),
            watch_resource_id = COALESCE(EXCLUDED.watch_resource_id,  integration_sync_state.watch_resource_id),
            updated_at        = now()
        RETURNING *
        """,
        _uuid.UUID(integration_id), calendar_id, sync_cursor,
        watch_channel_id, watch_expiry, watch_resource_id,
    )
    return _row(row)


async def delete_tasks_by_source(
    conn: asyncpg.Connection,
    user_id: str,
    source: str,
) -> int:
    """Hard-delete all tasks imported from a given source for this user.

    Called when the user disconnects an integration (e.g. Google Calendar)
    so that stale synced events don't persist in the calendar or plan view.

    Returns the number of tasks deleted.
    """
    # task_id columns in child tables have no FK REFERENCES tasks(uuid) ON DELETE CASCADE —
    # cleanup must be explicit. Use a subquery to batch-clean all child rows in one statement
    # before deleting the tasks themselves.
    task_id_subquery = "SELECT uuid::text FROM tasks WHERE user_id = $1::uuid AND source = $2"
    await conn.execute(
        f"DELETE FROM subtasks WHERE task_id IN ({task_id_subquery})", user_id, source
    )
    await conn.execute(
        f"DELETE FROM links WHERE parent_type = 'tasks' AND parent_id IN ({task_id_subquery})",
        user_id, source,
    )
    await conn.execute(
        f"""
        DELETE FROM dependencies
        WHERE (blocker_type = 'task' AND blocker_id IN ({task_id_subquery}))
           OR (blocked_type = 'task' AND blocked_id IN ({task_id_subquery}))
        """,
        user_id, source,
    )
    await conn.execute(
        f"DELETE FROM milestone_tasks WHERE task_id IN ({task_id_subquery})", user_id, source
    )
    await conn.execute(
        f"DELETE FROM followup_state WHERE task_id IN ({task_id_subquery})", user_id, source
    )
    result = await conn.execute(
        "DELETE FROM tasks WHERE user_id = $1::uuid AND source = $2",
        user_id, source,
    )
    # asyncpg returns "DELETE N" as the command tag
    try:
        return int(result.split()[-1])
    except (IndexError, ValueError):
        return 0


_ANTHROPIC_PROVIDER = "anthropic"


async def get_credentials_blob(
    conn: asyncpg.Connection,
    user_id: str,
) -> bytes | None:
    """Return raw credentials_blob bytes for 'anthropic' provider, or None."""
    row = await conn.fetchrow(
        "SELECT credentials_blob FROM user_integrations"
        " WHERE user_id = $1 AND provider = $2",
        user_id, _ANTHROPIC_PROVIDER,
    )
    if row is None:
        return None
    return row["credentials_blob"]


async def store_credentials_blob(
    conn: asyncpg.Connection,
    user_id: str,
    blob: bytes,
) -> None:
    """Upsert anthropic row setting credentials_blob.

    Uses ON CONFLICT (user_id, provider) to safely insert-or-update.
    """
    await conn.execute(
        """
        INSERT INTO user_integrations (user_id, provider, credentials_blob, enabled)
        VALUES ($1, $2, $3, true)
        ON CONFLICT (user_id, provider) DO UPDATE SET
            credentials_blob = EXCLUDED.credentials_blob
        """,
        user_id, _ANTHROPIC_PROVIDER, blob,
    )


async def delete_credentials_blob(
    conn: asyncpg.Connection,
    user_id: str,
) -> None:
    """DELETE the anthropic integration row for user_id."""
    await conn.execute(
        "DELETE FROM user_integrations WHERE user_id = $1 AND provider = $2",
        user_id, _ANTHROPIC_PROVIDER,
    )


async def soft_delete_task_by_external_id(
    conn: asyncpg.Connection,
    user_id: str,
    source: str,
    external_id: str,
) -> bool:
    result = await conn.execute(
        """
        UPDATE tasks
        SET source_status = 'cancelled'
        WHERE user_id = $1::uuid AND source = $2 AND external_id = $3
        """,
        user_id, source, external_id,
    )
    return result == "UPDATE 1"
