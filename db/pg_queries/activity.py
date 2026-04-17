"""Async Postgres queries — activity_leases table (stub).

activity_leases:
    id          BIGSERIAL PRIMARY KEY
    user_id     UUID NOT NULL
    session_id  TEXT
    source      TEXT
    op_class    TEXT
    scope       TEXT
    expires_at  TIMESTAMPTZ NOT NULL
    released    BOOL NOT NULL DEFAULT false
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
"""
from __future__ import annotations

import asyncpg


async def acquire_lease(
    conn: asyncpg.Connection,
    session_id: str,
    source: str,
    op_class: str,
    scope: str,
    ttl_seconds: int = 60,
) -> int:
    """Insert a new activity lease and return its id."""
    row = await conn.fetchrow(
        """
        INSERT INTO activity_leases
            (user_id, session_id, source, op_class, scope, expires_at)
        VALUES
            (current_setting('app.current_user_id', true)::uuid,
             $1, $2, $3, $4,
             now() + ($5 * interval '1 second'))
        RETURNING id
        """,
        session_id,
        source,
        op_class,
        scope,
        ttl_seconds,
    )
    return row["id"]


async def release_lease(conn: asyncpg.Connection, lease_id: int) -> None:
    """Mark a lease as released."""
    await conn.execute(
        """
        UPDATE activity_leases
        SET released = true
        WHERE id = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        lease_id,
    )


async def heartbeat_lease(
    conn: asyncpg.Connection, lease_id: int, ttl_seconds: int = 60
) -> None:
    """Extend a lease expiry."""
    await conn.execute(
        """
        UPDATE activity_leases
        SET expires_at = now() + ($1 * interval '1 second')
        WHERE id = $2
          AND user_id = current_setting('app.current_user_id', true)::uuid
          AND released = false
        """,
        ttl_seconds,
        lease_id,
    )


async def get_active_writers(
    conn: asyncpg.Connection, scope: str | None = None
) -> list[dict]:
    """Return active (non-expired, non-released) leases, optionally filtered by scope."""
    if scope is not None:
        rows = await conn.fetch(
            """
            SELECT id, session_id, source, op_class, scope, expires_at, created_at
            FROM activity_leases
            WHERE user_id = current_setting('app.current_user_id', true)::uuid
              AND released = false
              AND expires_at > now()
              AND scope = $1
            ORDER BY created_at
            """,
            scope,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, session_id, source, op_class, scope, expires_at, created_at
            FROM activity_leases
            WHERE user_id = current_setting('app.current_user_id', true)::uuid
              AND released = false
              AND expires_at > now()
            ORDER BY created_at
            """
        )
    return [dict(r) for r in rows]
