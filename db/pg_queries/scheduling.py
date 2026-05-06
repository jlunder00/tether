"""Scheduling queries — connections and meeting requests.

All functions take conn: asyncpg.Connection as first arg.
No SQLite, no file paths.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import asyncpg


def _row(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    return _convert(dict(row))


def _rows(rows) -> list[dict]:
    return [_row(r) for r in rows]


def _convert(d: dict) -> dict:
    """Recursively convert UUIDs to strings and UUID lists to str lists."""
    result = {}
    for k, v in d.items():
        if isinstance(v, _uuid.UUID):
            result[k] = str(v)
        elif isinstance(v, list):
            result[k] = [str(x) if isinstance(x, _uuid.UUID) else x for x in v]
        else:
            result[k] = v
    return result


def _canonical(uid1: str, uid2: str) -> tuple[str, str]:
    """Return (user_a, user_b) in canonical UUID order (user_a < user_b)."""
    a = _uuid.UUID(uid1)
    b = _uuid.UUID(uid2)
    if a < b:
        return str(a), str(b)
    return str(b), str(a)


# ─── Connection queries ────────────────────────────────────────────────────────

async def create_connection(
    conn: asyncpg.Connection,
    user_a_id: str,
    user_b_id: str,
    initiated_by: str,
) -> dict:
    a, b = _canonical(user_a_id, user_b_id)
    row = await conn.fetchrow(
        """
        INSERT INTO connections (user_a, user_b, initiated_by)
        VALUES ($1::uuid, $2::uuid, $3::uuid)
        RETURNING *
        """,
        a, b, initiated_by,
    )
    return _row(row)


async def get_connection(conn: asyncpg.Connection, conn_id: int) -> dict | None:
    row = await conn.fetchrow(
        "SELECT * FROM connections WHERE id = $1", conn_id
    )
    return _row(row)


async def get_connection_by_users(
    conn: asyncpg.Connection, uid1: str, uid2: str
) -> dict | None:
    a, b = _canonical(uid1, uid2)
    row = await conn.fetchrow(
        "SELECT * FROM connections WHERE user_a = $1::uuid AND user_b = $2::uuid",
        a, b,
    )
    return _row(row)


async def list_connections_for_user(
    conn: asyncpg.Connection, user_id: str
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT c.*,
               CASE WHEN c.user_a = $1::uuid THEN c.user_b ELSE c.user_a END AS other_user_id,
               CASE WHEN c.user_a = $1::uuid THEN u_b.username ELSE u_a.username END AS other_username
        FROM connections c
        LEFT JOIN users u_a ON u_a.id = c.user_a
        LEFT JOIN users u_b ON u_b.id = c.user_b
        WHERE c.user_a = $1::uuid OR c.user_b = $1::uuid
        ORDER BY c.created_at DESC
        """,
        user_id,
    )
    return _rows(rows)


async def accept_connection(conn: asyncpg.Connection, conn_id: int) -> dict:
    row = await conn.fetchrow(
        """
        UPDATE connections
        SET status = 'accepted', updated_at = now()
        WHERE id = $1
        RETURNING *
        """,
        conn_id,
    )
    return _row(row)


async def decline_connection(
    conn: asyncpg.Connection, conn_id: int, block: bool
) -> dict | None:
    if block:
        row = await conn.fetchrow(
            """
            UPDATE connections
            SET status = 'blocked', updated_at = now()
            WHERE id = $1
            RETURNING *
            """,
            conn_id,
        )
        return _row(row)
    else:
        await conn.execute("DELETE FROM connections WHERE id = $1", conn_id)
        return None


async def patch_connection(
    conn: asyncpg.Connection, conn_id: int, auto_schedule: bool
) -> dict:
    row = await conn.fetchrow(
        """
        UPDATE connections
        SET auto_schedule = $2, updated_at = now()
        WHERE id = $1
        RETURNING *
        """,
        conn_id, auto_schedule,
    )
    return _row(row)


# ─── Meeting queries ───────────────────────────────────────────────────────────

async def create_meeting_request(
    conn: asyncpg.Connection,
    initiator_id: str,
    target_ids: list[str],
    duration_minutes: int,
    context: str | None,
    slots: list[str],
) -> dict:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48)
    target_uuids = [_uuid.UUID(t) for t in target_ids]

    row = await conn.fetchrow(
        """
        INSERT INTO meeting_requests
            (initiator_id, target_ids, duration_minutes, context, expires_at)
        VALUES ($1::uuid, $2::uuid[], $3, $4, $5)
        RETURNING *
        """,
        initiator_id, target_uuids, duration_minutes, context, expires_at,
    )
    request = _row(row)

    # Store initiator's slots as first proposal
    if slots:
        await conn.execute(
            """
            INSERT INTO meeting_proposals (request_id, proposed_by, slots)
            VALUES ($1, $2::uuid, $3::text[])
            """,
            request["id"], initiator_id, slots,
        )

    return request


async def create_proposal(
    conn: asyncpg.Connection,
    request_id: int,
    proposed_by: str,
    slots: list[str],
    message: str | None,
) -> dict:
    # Mark previous pending proposals from same user as superseded
    await conn.execute(
        """
        UPDATE meeting_proposals
        SET status = 'superseded'
        WHERE request_id = $1 AND proposed_by = $2::uuid AND status = 'pending'
        """,
        request_id, proposed_by,
    )

    row = await conn.fetchrow(
        """
        INSERT INTO meeting_proposals (request_id, proposed_by, slots, message)
        VALUES ($1, $2::uuid, $3::text[], $4)
        RETURNING *
        """,
        request_id, proposed_by, slots, message,
    )
    proposal = _row(row)

    # Check if all targets have now proposed — bump round if so
    req_row = await conn.fetchrow(
        "SELECT target_ids, round FROM meeting_requests WHERE id = $1", request_id
    )
    if req_row:
        target_ids = [str(t) for t in req_row["target_ids"]]
        # Count targets with at least one active (non-superseded) proposal
        proposer_rows = await conn.fetch(
            """
            SELECT DISTINCT proposed_by FROM meeting_proposals
            WHERE request_id = $1
              AND status NOT IN ('superseded')
              AND proposed_by != (
                  SELECT initiator_id FROM meeting_requests WHERE id = $1
              )
            """,
            request_id,
        )
        proposers = {str(r["proposed_by"]) for r in proposer_rows}
        if set(target_ids) == proposers:
            new_round = req_row["round"] + 1
            await conn.execute(
                "UPDATE meeting_requests SET round = $2, updated_at = now() WHERE id = $1",
                request_id, new_round,
            )
            proposal["round_bumped"] = True

    return proposal


async def accept_meeting_slot(
    conn: asyncpg.Connection, request_id: int, slot: str
) -> dict:
    # Validate slot exists in a non-initiator proposal
    req_row = await conn.fetchrow(
        "SELECT initiator_id FROM meeting_requests WHERE id = $1", request_id
    )
    if not req_row:
        raise ValueError("Meeting request not found")

    initiator_id = req_row["initiator_id"]

    # Check slot exists in target proposals
    slot_row = await conn.fetchrow(
        """
        SELECT id FROM meeting_proposals
        WHERE request_id = $1
          AND proposed_by != $2::uuid
          AND status = 'pending'
          AND $3 = ANY(slots)
        LIMIT 1
        """,
        request_id, str(initiator_id), slot,
    )
    if not slot_row:
        raise ValueError(f"Slot '{slot}' not found in any pending target proposal")

    row = await conn.fetchrow(
        """
        UPDATE meeting_requests
        SET agreed_slot = $2, status = 'agreed', updated_at = now()
        WHERE id = $1
        RETURNING *
        """,
        request_id, slot,
    )
    return _row(row)


async def cancel_meeting(conn: asyncpg.Connection, request_id: int) -> dict:
    row = await conn.fetchrow(
        """
        UPDATE meeting_requests
        SET status = 'cancelled', updated_at = now()
        WHERE id = $1
        RETURNING *
        """,
        request_id,
    )
    return _row(row)


async def get_meeting_request(
    conn: asyncpg.Connection, request_id: int
) -> dict | None:
    row = await conn.fetchrow(
        "SELECT * FROM meeting_requests WHERE id = $1", request_id
    )
    if row is None:
        return None
    request = _row(row)

    # Fetch proposals
    proposal_rows = await conn.fetch(
        "SELECT * FROM meeting_proposals WHERE request_id = $1 ORDER BY created_at",
        request_id,
    )
    request["proposals"] = _rows(proposal_rows)
    return request


async def list_meetings_for_user(
    conn: asyncpg.Connection,
    user_id: str,
    status_filter: str | None = None,
) -> list[dict]:
    if status_filter:
        rows = await conn.fetch(
            """
            SELECT * FROM meeting_requests
            WHERE status = $1
            ORDER BY created_at DESC
            """,
            status_filter,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT * FROM meeting_requests
            ORDER BY created_at DESC
            """,
        )
    return _rows(rows)


async def list_incoming_for_user(
    conn: asyncpg.Connection, user_id: str
) -> list[dict]:
    """Return open meeting requests where user_id is in target_ids and has no pending proposal yet."""
    rows = await conn.fetch(
        """
        SELECT mr.* FROM meeting_requests mr
        WHERE mr.status = 'open'
          AND $1::uuid = ANY(mr.target_ids)
          AND NOT EXISTS (
              SELECT 1 FROM meeting_proposals mp
              WHERE mp.request_id = mr.id
                AND mp.proposed_by = $1::uuid
                AND mp.status IN ('pending', 'accepted')
          )
        ORDER BY mr.created_at DESC
        """,
        user_id,
    )
    return _rows(rows)


async def expire_old_requests(conn: asyncpg.Connection) -> list[int]:
    rows = await conn.fetch(
        """
        UPDATE meeting_requests
        SET status = 'expired', updated_at = now()
        WHERE status = 'open' AND expires_at < now()
        RETURNING id
        """,
    )
    return [r["id"] for r in rows]


def get_participants(request: dict) -> list[str]:
    """Return [initiator_id] + target_ids as strings."""
    result = [str(request["initiator_id"])]
    for t in request.get("target_ids", []):
        result.append(str(t))
    return result
