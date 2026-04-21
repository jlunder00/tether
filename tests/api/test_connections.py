"""Tests for /api/connections endpoints."""
from __future__ import annotations

import asyncpg
import pytest
from httpx import AsyncClient

from tests.api.conftest import TEST_USER_ID, TEST_USER_B_ID, TEST_USER_B_NAME


pytestmark = pytest.mark.asyncio


async def _create_connection_direct(conn) -> int:
    """Insert a connection directly using user A's conn (bypasses RLS via shared conn)."""
    from db.pg_queries.scheduling import create_connection
    result = await create_connection(conn, TEST_USER_ID, TEST_USER_B_ID, TEST_USER_ID)
    return result["id"]


# ─── POST /api/connections/request ────────────────────────────────────────────

async def test_create_connection_happy_path(api_client, api_client_b, conn, pool):
    """User A requests a connection to User B."""
    resp = await api_client.post("/api/connections/request", json={"target_username": TEST_USER_B_NAME})
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["initiated_by"] == TEST_USER_ID
    # Canonical ordering: user_a < user_b (UUID string comparison)
    assert data["user_a"] < data["user_b"]


async def test_create_connection_canonical_ordering(api_client, api_client_b, conn, pool):
    """Canonical ordering is enforced regardless of who requests."""
    # B requests A — same canonical result
    resp = await api_client_b.post("/api/connections/request", json={"target_username": "testuser"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["user_a"] < data["user_b"]
    assert data["initiated_by"] == TEST_USER_B_ID


async def test_create_connection_404_unknown_target(api_client, conn):
    resp = await api_client.post("/api/connections/request", json={"target_username": "no_such_user"})
    assert resp.status_code == 404


async def test_create_connection_409_duplicate(api_client, conn):
    """Second request between same users returns 409."""
    resp1 = await api_client.post("/api/connections/request", json={"target_username": TEST_USER_B_NAME})
    assert resp1.status_code == 201
    resp2 = await api_client.post("/api/connections/request", json={"target_username": TEST_USER_B_NAME})
    assert resp2.status_code == 409


# ─── POST /api/connections/{id}/accept ────────────────────────────────────────

async def test_accept_connection(api_client, api_client_b, conn, pool):
    conn_id = await _create_connection_direct(conn)
    resp = await api_client_b.post(f"/api/connections/{conn_id}/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


async def test_accept_connection_403_initiator(api_client, conn):
    """Initiator cannot accept their own request."""
    conn_id = await _create_connection_direct(conn)
    resp = await api_client.post(f"/api/connections/{conn_id}/accept")
    assert resp.status_code == 403


async def test_accept_connection_404_missing(api_client_b, conn):
    resp = await api_client_b.post("/api/connections/99999/accept")
    assert resp.status_code == 404


# ─── POST /api/connections/{id}/decline ───────────────────────────────────────

async def test_decline_connection_delete(api_client_b, conn, pool):
    conn_id = await _create_connection_direct(conn)
    resp = await api_client_b.post(f"/api/connections/{conn_id}/decline", json={"block": False})
    assert resp.status_code == 200
    assert resp.json().get("deleted") is True


async def test_decline_connection_block(api_client_b, conn, pool):
    conn_id = await _create_connection_direct(conn)
    resp = await api_client_b.post(f"/api/connections/{conn_id}/decline", json={"block": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "blocked"


async def test_decline_connection_403_initiator(api_client, conn):
    """Initiator cannot decline their own request."""
    conn_id = await _create_connection_direct(conn)
    resp = await api_client.post(f"/api/connections/{conn_id}/decline", json={"block": False})
    assert resp.status_code == 403


# ─── GET /api/connections ─────────────────────────────────────────────────────

async def test_list_connections(api_client, conn):
    await _create_connection_direct(conn)
    resp = await api_client.get("/api/connections")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Each item should have other_user_id
    assert "other_user_id" in data[0]


# ─── PATCH /api/connections/{id} ──────────────────────────────────────────────

async def test_patch_connection_auto_schedule(api_client, conn):
    conn_id = await _create_connection_direct(conn)
    resp = await api_client.patch(f"/api/connections/{conn_id}", json={"auto_schedule": False})
    assert resp.status_code == 200
    assert resp.json()["auto_schedule"] is False


async def test_patch_connection_404_missing(api_client, conn):
    resp = await api_client.patch("/api/connections/99999", json={"auto_schedule": False})
    assert resp.status_code == 404
