"""Tests for POST /api/meetings/{id}/finalize endpoint.

TDD: these tests were written BEFORE the handler was implemented.

Idempotency note: implemented via task-tag search `[meeting:{id}]` rather than
bot_actions table — bot_actions (PR 2) is not a dependency for this endpoint.

RLS note: non-participants cannot see meeting_requests rows (RLS filters them),
so the explicit 403 participant check is defense-in-depth. In practice, a
non-participant calling finalize receives 404 (row not visible), not 403.
The 403 test below uses this fact directly.
"""
from __future__ import annotations

import re
import pytest
from datetime import datetime, timezone, timedelta

from tests.api.conftest import (
    TEST_USER_ID,
    TEST_USER_B_ID,
    TEST_USER_B_NAME,
    TEST_USERNAME,
)

pytestmark = pytest.mark.asyncio

# An already-agreed slot far in the future so plan_date is predictable.
AGREED_SLOT = "2027-06-15T09:00:00Z"
AGREED_SLOT_DATE = "2027-06-15"
DURATION = 30


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _setup_accepted_connection(conn) -> None:
    from db.pg_queries.scheduling import create_connection, accept_connection
    c = await create_connection(conn, TEST_USER_ID, TEST_USER_B_ID, TEST_USER_ID)
    await accept_connection(conn, c["id"])


async def _create_agreed_meeting(conn) -> int:
    """Insert an agreed meeting directly — bypasses proposal flow."""
    import uuid
    # Insert agreed meeting
    row = await conn.fetchrow(
        """
        INSERT INTO meeting_requests
            (initiator_id, target_ids, duration_minutes, context,
             status, agreed_slot, expires_at)
        VALUES
            ($1::uuid, $2::uuid[], $3, $4,
             'agreed', $5, now() + interval '48 hours')
        RETURNING id
        """,
        TEST_USER_ID,
        [uuid.UUID(TEST_USER_B_ID)],
        DURATION,
        "IGNORE THIS CONTEXT — should never appear in task body",
        AGREED_SLOT,
    )
    return row["id"]


async def _create_open_meeting(conn) -> int:
    """Insert an open (non-agreed) meeting."""
    import uuid
    row = await conn.fetchrow(
        """
        INSERT INTO meeting_requests
            (initiator_id, target_ids, duration_minutes,
             status, expires_at)
        VALUES
            ($1::uuid, $2::uuid[], $3,
             'open', now() + interval '48 hours')
        RETURNING id
        """,
        TEST_USER_ID,
        [uuid.UUID(TEST_USER_B_ID)],
        DURATION,
    )
    return row["id"]


# ─── Test 1: 404 if meeting doesn't exist ─────────────────────────────────────

async def test_finalize_404_meeting_not_found(api_client, conn):
    resp = await api_client.post("/api/meetings/99999/finalize")
    assert resp.status_code == 404


# ─── Test 2: 400 if meeting not in agreed status ──────────────────────────────

async def test_finalize_400_not_agreed_status(api_client, conn):
    meeting_id = await _create_open_meeting(conn)
    resp = await api_client.post(f"/api/meetings/{meeting_id}/finalize")
    assert resp.status_code == 400
    assert "agreed" in resp.json()["detail"].lower()


# ─── Test 3: Non-participant cannot finalize (404 via RLS) ────────────────────

async def test_finalize_403_nonparticipant(api_client_b, conn):
    """A user who is not the initiator or any target gets 403.

    When RLS is properly enforced, a non-participant cannot see the meeting row
    at all (returns None → 404). However, CI runs under a superuser role where
    RLS is bypassed (known issue: tether_app is a superuser), so the row IS
    visible and the explicit 403 participant check in the handler fires instead.

    The handler's 403 check is therefore the correct observable behaviour in all
    current test environments. This test asserts 403 to match the enforced check.
    """
    import uuid as uuid_mod

    # Insert a meeting between user A (initiator) and a ghost user (not B)
    ghost_id = "00000000-0000-0000-0000-000000000099"
    # First ensure ghost user exists (foreign key constraint)
    await conn.execute(
        """
        INSERT INTO users (id, username, email, password_hash)
        VALUES ($1::uuid, 'ghostuser', 'ghost@example.com', 'x')
        ON CONFLICT (id) DO NOTHING
        """,
        ghost_id,
    )
    row = await conn.fetchrow(
        """
        INSERT INTO meeting_requests
            (initiator_id, target_ids, duration_minutes,
             status, agreed_slot, expires_at)
        VALUES
            ($1::uuid, $2::uuid[], $3,
             'agreed', $4, now() + interval '48 hours')
        RETURNING id
        """,
        TEST_USER_ID,
        [uuid_mod.UUID(ghost_id)],
        DURATION,
        AGREED_SLOT,
    )
    meeting_id = row["id"]

    # User B is NOT a participant — explicit 403 check fires
    resp = await api_client_b.post(f"/api/meetings/{meeting_id}/finalize")
    assert resp.status_code == 403


# ─── Test 4: Happy path — task created with [meeting:id] tag ──────────────────

async def test_finalize_creates_task_with_meeting_tag(api_client, conn):
    """Successful finalize returns 201, task_id, status='created', and
    the task body contains [meeting:{id}] and NOT the context field text."""
    meeting_id = await _create_agreed_meeting(conn)
    resp = await api_client.post(f"/api/meetings/{meeting_id}/finalize")
    assert resp.status_code == 201
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "created"

    # Verify the task exists in DB with correct tag
    task_row = await conn.fetchrow(
        "SELECT text, plan_date, start_time FROM tasks WHERE uuid = $1::uuid",
        data["task_id"],
    )
    assert task_row is not None
    task_text = task_row["text"]
    assert f"[meeting:{meeting_id}]" in task_text
    assert task_row["plan_date"] == AGREED_SLOT_DATE
    assert task_row["start_time"] is not None

    # Duration minutes present in task body
    assert f"{DURATION}min" in task_text


# ─── Test 5: Context field NOT in task body (injection defense) ───────────────

async def test_finalize_context_not_in_task_body(api_client, conn):
    """The meeting.context field must never appear in the task text.
    Defense against prompt injection: task body is assembled from structured
    DB fields only (agreed_slot, duration, participant usernames, meeting id).
    """
    meeting_id = await _create_agreed_meeting(conn)
    resp = await api_client.post(f"/api/meetings/{meeting_id}/finalize")
    assert resp.status_code == 201

    task_row = await conn.fetchrow(
        "SELECT text FROM tasks WHERE uuid = $1::uuid",
        resp.json()["task_id"],
    )
    # The context string contains "CONTEXT" — must not appear in task text
    assert "IGNORE THIS CONTEXT" not in task_row["text"]


# ─── Test 6: Idempotent — second call returns existing task ───────────────────

async def test_finalize_idempotent(api_client, conn):
    """Second finalize by same user returns 200 with status='already_exists'
    and the same task_id — no duplicate task created."""
    meeting_id = await _create_agreed_meeting(conn)

    resp1 = await api_client.post(f"/api/meetings/{meeting_id}/finalize")
    assert resp1.status_code == 201
    task_id_1 = resp1.json()["task_id"]

    resp2 = await api_client.post(f"/api/meetings/{meeting_id}/finalize")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "already_exists"
    assert data2["task_id"] == task_id_1

    # Confirm only one task in DB with this tag
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM tasks WHERE text LIKE $1",
        f"%[meeting:{meeting_id}]%",
    )
    assert count == 1


# ─── Test 7: Two participants each get their own task ─────────────────────────

async def test_finalize_two_participants_get_separate_tasks(
    api_client, api_client_b, conn
):
    """User A and user B both finalize the same meeting → two separate tasks,
    one per user, each with [meeting:{id}] tag."""
    meeting_id = await _create_agreed_meeting(conn)

    resp_a = await api_client.post(f"/api/meetings/{meeting_id}/finalize")
    assert resp_a.status_code == 201

    resp_b = await api_client_b.post(f"/api/meetings/{meeting_id}/finalize")
    assert resp_b.status_code == 201

    task_id_a = resp_a.json()["task_id"]
    task_id_b = resp_b.json()["task_id"]
    assert task_id_a != task_id_b

    # Verify distinct owners via user_id column
    row_a = await conn.fetchrow(
        "SELECT user_id FROM tasks WHERE uuid = $1::uuid", task_id_a
    )
    row_b = await conn.fetchrow(
        "SELECT user_id FROM tasks WHERE uuid = $1::uuid", task_id_b
    )
    assert str(row_a["user_id"]) == TEST_USER_ID
    assert str(row_b["user_id"]) == TEST_USER_B_ID


# ─── Test 8: Task body mentions other participants, not caller ────────────────

async def test_finalize_task_mentions_other_participants(api_client, conn):
    """Task body lists @mentions of OTHER participants (not the caller).
    Caller is user A (TEST_USER_ID / 'testuser'); meeting target is user B.
    A's task should mention @testuser2 (B) but not @testuser (A) in @mentions.
    """
    meeting_id = await _create_agreed_meeting(conn)
    resp = await api_client.post(f"/api/meetings/{meeting_id}/finalize")
    assert resp.status_code == 201

    task_row = await conn.fetchrow(
        "SELECT text FROM tasks WHERE uuid = $1::uuid",
        resp.json()["task_id"],
    )
    text = task_row["text"]
    # Extract all @mention tokens — avoids substring false-positives.
    # e.g. "testuser" is a prefix of "testuser2", so `in` would wrongly match;
    # token-based comparison is exact.
    mention_tokens = re.findall(r"@\w+", text)
    assert f"@{TEST_USER_B_NAME}" in mention_tokens   # other participant mentioned
    assert f"@{TEST_USERNAME}" not in mention_tokens   # caller NOT self-mentioned
