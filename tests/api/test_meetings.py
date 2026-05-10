"""Tests for /api/meetings endpoints."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from tests.api.conftest import TEST_USER_ID, TEST_USER_B_ID, TEST_USER_B_NAME


pytestmark = pytest.mark.asyncio

SAMPLE_SLOTS = ["2026-05-01T10:00:00Z", "2026-05-01T14:00:00Z"]


async def _setup_accepted_connection(conn) -> int:
    """Insert an accepted connection between user A and user B."""
    from db.pg_queries.scheduling import create_connection, accept_connection
    c = await create_connection(conn, TEST_USER_ID, TEST_USER_B_ID, TEST_USER_ID)
    result = await accept_connection(conn, c["id"])
    return result["id"]


async def _create_meeting(api_client, conn) -> dict:
    """Create a meeting request from user A to user B (requires accepted connection)."""
    await _setup_accepted_connection(conn)
    resp = await api_client.post(
        "/api/meetings/request",
        json={
            "target_usernames": [TEST_USER_B_NAME],
            "duration_minutes": 30,
            "slots": SAMPLE_SLOTS,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── POST /api/meetings/request ───────────────────────────────────────────────

async def test_create_meeting_happy_path(api_client, conn):
    meeting = await _create_meeting(api_client, conn)
    assert meeting["status"] == "open"
    assert "id" in meeting


async def test_create_meeting_400_no_accepted_connection(api_client, conn):
    """Creating meeting without accepted connection returns 400."""
    resp = await api_client.post(
        "/api/meetings/request",
        json={
            "target_usernames": [TEST_USER_B_NAME],
            "duration_minutes": 30,
            "slots": SAMPLE_SLOTS,
        },
    )
    assert resp.status_code == 400


async def test_create_meeting_400_empty_slots(api_client, conn):
    await _setup_accepted_connection(conn)
    resp = await api_client.post(
        "/api/meetings/request",
        json={
            "target_usernames": [TEST_USER_B_NAME],
            "duration_minutes": 30,
            "slots": [],
        },
    )
    assert resp.status_code == 400


async def test_create_meeting_404_unknown_target(api_client, conn):
    resp = await api_client.post(
        "/api/meetings/request",
        json={
            "target_usernames": ["no_such_user"],
            "duration_minutes": 30,
            "slots": SAMPLE_SLOTS,
        },
    )
    assert resp.status_code == 404


# ─── POST /api/meetings/{id}/propose ──────────────────────────────────────────

async def test_propose_happy_path(api_client, api_client_b, conn, pool):
    meeting = await _create_meeting(api_client, conn)
    meeting_id = meeting["id"]

    resp = await api_client_b.post(
        f"/api/meetings/{meeting_id}/propose",
        json={"slots": ["2026-05-01T11:00:00Z"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "proposal_id" in data
    assert data["request_id"] == meeting_id


async def test_propose_403_initiator(api_client, conn):
    """Initiator cannot propose on their own meeting."""
    meeting = await _create_meeting(api_client, conn)
    resp = await api_client.post(
        f"/api/meetings/{meeting['id']}/propose",
        json={"slots": SAMPLE_SLOTS},
    )
    assert resp.status_code == 403


async def test_propose_404_missing(api_client_b, conn):
    resp = await api_client_b.post(
        "/api/meetings/99999/propose",
        json={"slots": SAMPLE_SLOTS},
    )
    assert resp.status_code == 404


async def test_propose_supersedes_previous(api_client, api_client_b, conn, pool):
    """Second proposal from same user supersedes the first."""
    meeting = await _create_meeting(api_client, conn)
    meeting_id = meeting["id"]

    await api_client_b.post(
        f"/api/meetings/{meeting_id}/propose",
        json={"slots": ["2026-05-01T11:00:00Z"]},
    )
    await api_client_b.post(
        f"/api/meetings/{meeting_id}/propose",
        json={"slots": ["2026-05-02T11:00:00Z"]},
    )

    # Get the meeting and check only one pending proposal from B
    from db.pg_queries.scheduling import get_meeting_request
    req = await get_meeting_request(conn, meeting_id)
    b_proposals = [p for p in req["proposals"] if p["proposed_by"] == TEST_USER_B_ID]
    pending_b = [p for p in b_proposals if p["status"] == "pending"]
    assert len(pending_b) == 1
    assert pending_b[0]["slots"] == ["2026-05-02T11:00:00Z"]


async def test_propose_round_increments(api_client, api_client_b, conn, pool):
    """Round increments when all targets have proposed."""
    meeting = await _create_meeting(api_client, conn)
    meeting_id = meeting["id"]

    # Before proposal, round is 0
    from db.pg_queries.scheduling import get_meeting_request
    req = await get_meeting_request(conn, meeting_id)
    assert req["round"] == 0

    # B proposes — now all targets have proposed (only B is a target)
    await api_client_b.post(
        f"/api/meetings/{meeting_id}/propose",
        json={"slots": ["2026-05-01T11:00:00Z"]},
    )

    req = await get_meeting_request(conn, meeting_id)
    assert req["round"] == 1


# ─── POST /api/meetings/{id}/accept ───────────────────────────────────────────

async def test_accept_slot_happy_path(api_client, api_client_b, conn, pool):
    meeting = await _create_meeting(api_client, conn)
    meeting_id = meeting["id"]
    target_slot = "2026-05-01T11:00:00Z"

    await api_client_b.post(
        f"/api/meetings/{meeting_id}/propose",
        json={"slots": [target_slot]},
    )

    resp = await api_client.post(
        f"/api/meetings/{meeting_id}/accept",
        json={"slot": target_slot},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "agreed"
    assert data["agreed_slot"] == target_slot


async def test_accept_slot_403_not_initiator(api_client_b, conn, pool):
    """Only initiator can accept a slot."""
    from db.pg_queries.scheduling import create_meeting_request
    await _setup_accepted_connection(conn)
    req = await create_meeting_request(
        conn, TEST_USER_ID, [TEST_USER_B_ID], 30, None, SAMPLE_SLOTS
    )
    meeting_id = req["id"]

    resp = await api_client_b.post(
        f"/api/meetings/{meeting_id}/accept",
        json={"slot": SAMPLE_SLOTS[0]},
    )
    assert resp.status_code == 403


async def test_accept_slot_400_slot_not_in_proposals(api_client, conn):
    """Accepting a slot that's not in any proposal returns 400."""
    meeting = await _create_meeting(api_client, conn)
    resp = await api_client.post(
        f"/api/meetings/{meeting['id']}/accept",
        json={"slot": "2026-12-31T00:00:00Z"},
    )
    assert resp.status_code == 400


# ─── POST /api/meetings/{id}/cancel ───────────────────────────────────────────

async def test_cancel_meeting(api_client, conn):
    meeting = await _create_meeting(api_client, conn)
    resp = await api_client.post(f"/api/meetings/{meeting['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


# ─── GET /api/meetings ────────────────────────────────────────────────────────

async def test_list_meetings(api_client, conn):
    await _create_meeting(api_client, conn)
    resp = await api_client.get("/api/meetings")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


async def test_list_meetings_status_filter(api_client, conn):
    await _create_meeting(api_client, conn)
    resp = await api_client.get("/api/meetings?status=open")
    assert resp.status_code == 200
    for item in resp.json():
        assert item["status"] == "open"


# ─── GET /api/meetings/incoming ───────────────────────────────────────────────

async def test_list_incoming(api_client, api_client_b, conn, pool):
    meeting = await _create_meeting(api_client, conn)
    resp = await api_client_b.get("/api/meetings/incoming")
    assert resp.status_code == 200
    data = resp.json()
    ids = [m["id"] for m in data]
    assert meeting["id"] in ids


# ─── GET /api/meetings/{id} ───────────────────────────────────────────────────

async def test_get_meeting(api_client, conn):
    meeting = await _create_meeting(api_client, conn)
    resp = await api_client.get(f"/api/meetings/{meeting['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == meeting["id"]
    assert "proposals" in data


async def test_get_meeting_404_missing(api_client, conn):
    resp = await api_client.get("/api/meetings/99999")
    assert resp.status_code == 404


# ─── expire_old_requests unit test ────────────────────────────────────────────

async def test_expire_old_requests(conn):
    """Manually insert a meeting with past expires_at, verify it gets expired."""
    import uuid
    from db.pg_queries.scheduling import expire_old_requests

    # Insert past-expired meeting directly
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    row = await conn.fetchrow(
        """
        INSERT INTO meeting_requests (initiator_id, target_ids, duration_minutes, expires_at, status)
        VALUES ($1::uuid, $2::uuid[], 30, $3, 'open')
        RETURNING id
        """,
        TEST_USER_ID,
        [uuid.UUID(TEST_USER_B_ID)],
        past,
    )
    req_id = row["id"]

    expired_ids = await expire_old_requests(conn)
    assert req_id in expired_ids

    # Verify status
    row2 = await conn.fetchrow("SELECT status FROM meeting_requests WHERE id = $1", req_id)
    assert row2["status"] == "expired"

# ─── N+1 batch-query assertions ───────────────────────────────────────────────

async def test_request_meeting_uses_batch_username_resolution(api_client, conn):
    """POST /meetings/request must use get_users_by_usernames, not get_user_by_username."""
    from unittest.mock import patch
    await _setup_accepted_connection(conn)
    with patch(
        "api.routes.meetings.get_user_by_username",
        side_effect=AssertionError("get_user_by_username called — batch not used"),
    ):
        resp = await api_client.post(
            "/api/meetings/request",
            json={
                "target_usernames": [TEST_USER_B_NAME],
                "duration_minutes": 30,
                "slots": SAMPLE_SLOTS,
            },
        )
    assert resp.status_code == 201


async def test_accept_slot_uses_batch_user_lookup(api_client, api_client_b, conn, pool):
    """POST /meetings/{id}/accept must use get_users_by_ids, not get_user_by_id."""
    from unittest.mock import patch
    meeting = await _create_meeting(api_client, conn)
    meeting_id = meeting["id"]
    await api_client_b.post(
        f"/api/meetings/{meeting_id}/propose",
        json={"slots": [SAMPLE_SLOTS[0]]},
    )
    with patch(
        "api.routes.meetings.get_user_by_id",
        side_effect=AssertionError("get_user_by_id called — batch not used"),
    ):
        resp = await api_client.post(
            f"/api/meetings/{meeting_id}/accept",
            json={"slot": SAMPLE_SLOTS[0]},
        )
    assert resp.status_code == 200
