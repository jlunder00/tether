"""Async Postgres queries — state_monitor_log table.

state_monitor_log:
    id          BIGSERIAL PRIMARY KEY
    user_id     UUID NOT NULL
    change_type TEXT NOT NULL
    entity_id   TEXT NOT NULL
    score       INT  NOT NULL DEFAULT 1
    consumed    BOOL NOT NULL DEFAULT false
    ts          TIMESTAMPTZ NOT NULL DEFAULT now()
"""
from __future__ import annotations

import uuid as _uuid

import asyncpg

CHANGE_WEIGHTS: dict[str, int] = {
    "task_done":          2,
    "task_blocked":       2,
    "context_updated":    3,
    "plan_restructured":  5,
    "acknowledgement":    1,
    "task_created":       1,
}
_DEFAULT_WEIGHT = 1
DEBOUNCE_MINUTES = 10


async def record_change(
    conn: asyncpg.Connection,
    user_id: str,
    change_type: str,
    entity_id: str,
    score: int | None = None,
) -> None:
    """Record a raw state change event."""
    if score is None:
        score = CHANGE_WEIGHTS.get(change_type, _DEFAULT_WEIGHT)
    await conn.execute(
        """
        INSERT INTO state_monitor_log (user_id, change_type, entity_id, score)
        VALUES ($1, $2, $3, $4)
        """,
        _uuid.UUID(user_id),
        change_type,
        entity_id,
        score,
    )


async def get_pending_score(
    conn: asyncpg.Connection,
    user_id: str,
    debounce_minutes: int = DEBOUNCE_MINUTES,
) -> int:
    """Score of unconsumed changes, deduplicated by (change_type, entity_id).

    Only counts changes older than the debounce window so in-progress bot
    actions don't inflate the score.
    """
    row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(max_score), 0) AS total
        FROM (
            SELECT MAX(score) AS max_score
            FROM state_monitor_log
            WHERE user_id = $1
              AND consumed = false
              AND ts <= now() - ($2 * interval '1 minute')
            GROUP BY change_type, entity_id
        ) sub
        """,
        _uuid.UUID(user_id),
        debounce_minutes,
    )
    return int(row["total"])


async def get_window_age_minutes(
    conn: asyncpg.Connection, user_id: str
) -> float | None:
    """Minutes since the oldest unconsumed change, or None if no pending changes."""
    row = await conn.fetchrow(
        """
        SELECT EXTRACT(EPOCH FROM (now() - MIN(ts))) / 60 AS age_minutes
        FROM state_monitor_log
        WHERE user_id = $1
          AND consumed = false
        """,
        _uuid.UUID(user_id),
    )
    if not row or row["age_minutes"] is None:
        return None
    return float(row["age_minutes"])


async def is_window_settled(
    conn: asyncpg.Connection,
    user_id: str,
    settle_minutes: int = DEBOUNCE_MINUTES,
) -> bool:
    """True if there are pending changes AND no unconsumed rows in the last
    settle_minutes (debounce window has passed)."""
    uid = _uuid.UUID(user_id)

    has_pending = await conn.fetchval(
        """
        SELECT 1 FROM state_monitor_log
        WHERE user_id = $1 AND consumed = false
        LIMIT 1
        """,
        uid,
    )
    if not has_pending:
        return False

    recent = await conn.fetchval(
        """
        SELECT 1 FROM state_monitor_log
        WHERE user_id = $1
          AND consumed = false
          AND ts > now() - ($2 * interval '1 minute')
        LIMIT 1
        """,
        uid,
        settle_minutes,
    )
    # Settled = no changes within the debounce window
    return recent is None


async def peek_changes(
    conn: asyncpg.Connection, user_id: str, limit: int = 50
) -> list[dict]:
    """Return pending changes WITHOUT marking them consumed."""
    rows = await conn.fetch(
        """
        SELECT id, change_type, entity_id, score, ts
        FROM state_monitor_log
        WHERE user_id = $1
          AND consumed = false
        ORDER BY ts DESC
        LIMIT $2
        """,
        _uuid.UUID(user_id),
        limit,
    )
    return [dict(r) for r in rows]


async def consume_changes(
    conn: asyncpg.Connection, user_id: str
) -> list[dict]:
    """Mark all pending changes as consumed and return their summaries."""
    rows = await conn.fetch(
        """
        SELECT id, change_type, entity_id, score, ts
        FROM state_monitor_log
        WHERE user_id = $1
          AND consumed = false
        ORDER BY ts
        """,
        _uuid.UUID(user_id),
    )
    changes = [dict(r) for r in rows]
    if changes:
        ids = [c["id"] for c in changes]
        await conn.execute(
            """
            UPDATE state_monitor_log
            SET consumed = true
            WHERE user_id = $1
              AND id = ANY($2)
            """,
            _uuid.UUID(user_id),
            ids,
        )
    return changes
