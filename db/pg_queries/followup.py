"""Async Postgres queries — followup_state, acknowledgements, check_ins tables."""
from __future__ import annotations

from datetime import datetime
import uuid as _uuid

import asyncpg


# ---------------------------------------------------------------------------
# followup_state
# ---------------------------------------------------------------------------


async def init_followup_state(
    conn: asyncpg.Connection,
    date: str,
    anchor_id: str,
    task_id: str,
    now: datetime,
) -> None:
    """INSERT … ON CONFLICT DO NOTHING — idempotent, won't reset existing state."""
    await conn.execute(
        """
        INSERT INTO followup_state
            (user_id, date, anchor_id, task_id, sequence_started_at)
        VALUES
            (current_setting('app.current_user_id', true)::uuid, $1, $2, $3, $4)
        ON CONFLICT (user_id, date, anchor_id, task_id) DO NOTHING
        """,
        date,
        anchor_id,
        task_id,
        now,
    )


async def get_active_followup_states(
    conn: asyncpg.Connection, date: str
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT *
        FROM followup_state
        WHERE date = $1
          AND completed = false
          AND user_id = current_setting('app.current_user_id', true)::uuid
        ORDER BY id
        """,
        date,
    )
    return [dict(r) for r in rows]


async def acknowledge_followup(
    conn: asyncpg.Connection, date: str, anchor_id: str, now: datetime
) -> None:
    """Set acknowledged_at on all unacked rows for this anchor today."""
    await conn.execute(
        """
        UPDATE followup_state
        SET acknowledged_at = $1
        WHERE date = $2
          AND anchor_id = $3
          AND acknowledged_at IS NULL
          AND completed = false
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        now,
        date,
        anchor_id,
    )


async def record_ping(
    conn: asyncpg.Connection, row_id: int, phase: str, now: datetime
) -> None:
    """Increment pre_ack_pings_sent or post_ack_pings_sent and update last_ping_at."""
    if phase == "pre":
        await conn.execute(
            """
            UPDATE followup_state
            SET pre_ack_pings_sent = pre_ack_pings_sent + 1,
                last_ping_at = $1
            WHERE id = $2
              AND user_id = current_setting('app.current_user_id', true)::uuid
            """,
            now,
            row_id,
        )
    else:
        await conn.execute(
            """
            UPDATE followup_state
            SET post_ack_pings_sent = post_ack_pings_sent + 1,
                last_ping_at = $1
            WHERE id = $2
              AND user_id = current_setting('app.current_user_id', true)::uuid
            """,
            now,
            row_id,
        )


async def mark_followup_completed(
    conn: asyncpg.Connection, task_id: str, date: str
) -> None:
    await conn.execute(
        """
        UPDATE followup_state
        SET completed = true
        WHERE task_id = $1
          AND date = $2
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        task_id,
        date,
    )


async def resolve_followup_config(
    conn: asyncpg.Connection, anchor_id: str, task_id: str
) -> dict | None:
    """Return resolved FollowupConfig: task overrides anchor, None if neither enabled."""
    task_row = await conn.fetchrow(
        """
        SELECT followup_config FROM tasks
        WHERE uuid = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        _uuid.UUID(task_id),
    )
    anchor_row = await conn.fetchrow(
        """
        SELECT followup_config FROM anchors
        WHERE id = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        _uuid.UUID(anchor_id),
    )
    task_fc = task_row["followup_config"] if task_row else None    # already dict from JSONB
    anchor_fc = anchor_row["followup_config"] if anchor_row else None
    config = task_fc or anchor_fc
    if not config or not config.get("enabled"):
        return None
    return config


# ---------------------------------------------------------------------------
# acknowledgements
# ---------------------------------------------------------------------------


async def get_acknowledgements(
    conn: asyncpg.Connection, plan_date: str
) -> dict[str, str]:
    """Return {anchor_id: acknowledged_at} for a given plan date."""
    rows = await conn.fetch(
        """
        SELECT anchor_id, acknowledged_at
        FROM acknowledgements
        WHERE plan_date = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        """,
        plan_date,
    )
    return {r["anchor_id"]: r["acknowledged_at"] for r in rows}


async def upsert_acknowledgement(
    conn: asyncpg.Connection,
    plan_date: str,
    anchor_id: str,
    acknowledged_at: datetime,
) -> None:
    await conn.execute(
        """
        INSERT INTO acknowledgements (user_id, plan_date, anchor_id, acknowledged_at)
        VALUES (current_setting('app.current_user_id', true)::uuid, $1, $2, $3)
        ON CONFLICT (user_id, plan_date, anchor_id) DO UPDATE SET
            acknowledged_at = EXCLUDED.acknowledged_at
        """,
        plan_date,
        anchor_id,
        acknowledged_at,
    )


# ---------------------------------------------------------------------------
# check_ins
# ---------------------------------------------------------------------------


async def insert_check_in(
    conn: asyncpg.Connection,
    date: str,
    anchor_id: str,
    accomplished: str,
    current_status: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO check_ins
            (user_id, plan_date, anchor_id, type, timestamp, accomplished, current_status)
        VALUES
            (current_setting('app.current_user_id', true)::uuid,
             $1, $2, 'user_checkin', now(), $3, $4)
        """,
        date,
        anchor_id,
        accomplished,
        current_status,
    )


async def get_check_ins(conn: asyncpg.Connection, plan_date: str) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT *
        FROM check_ins
        WHERE plan_date = $1
          AND user_id = current_setting('app.current_user_id', true)::uuid
        ORDER BY timestamp
        """,
        plan_date,
    )
    return [dict(r) for r in rows]
