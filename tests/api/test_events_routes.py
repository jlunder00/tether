"""Tests for GET/POST /api/events endpoints."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _insert_task(conn, text: str = "Test event task") -> str:
    """Insert a bare task and return its UUID string."""
    row = await conn.fetchrow(
        """
        INSERT INTO tasks (uuid, user_id, text, status)
        VALUES (
            gen_random_uuid(),
            current_setting('app.current_user_id', true)::uuid,
            $1,
            'pending'
        )
        RETURNING uuid
        """,
        text,
    )
    return str(row["uuid"])


# ─── POST /api/events ─────────────────────────────────────────────────────────

async def test_post_event_promotes_task(api_client, conn):
    task_id = await _insert_task(conn)

    resp = await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-04-25T09:00:00Z",
        "end_time": "2026-04-25T10:00:00Z",
        "title": "Test event task",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["id"] == task_id
    assert data["task_id"] == task_id
    assert data["start_time"] is not None
    assert data["end_time"] is not None
    assert data["source"] == "tether"
    assert data["external_id"] is None


async def test_post_event_idempotent(api_client, conn):
    """Promoting the same task twice updates the time rather than erroring."""
    task_id = await _insert_task(conn)

    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-04-25T09:00:00Z",
        "end_time": "2026-04-25T10:00:00Z",
        "title": "Test event task",
    })
    resp = await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-04-25T14:00:00Z",
        "end_time": "2026-04-25T15:00:00Z",
        "title": "Test event task",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "14:00" in data["start_time"] or "14" in data["start_time"]


async def test_post_event_404_unknown_task(api_client, conn):
    resp = await api_client.post("/api/events", json={
        "task_id": "00000000-0000-0000-0000-000000000099",
        "start_time": "2026-04-25T09:00:00Z",
        "end_time": "2026-04-25T10:00:00Z",
        "title": "Ghost",
    })
    assert resp.status_code == 404


async def test_post_event_422_missing_fields(api_client, conn):
    resp = await api_client.post("/api/events", json={"task_id": "abc"})
    assert resp.status_code == 422


# ─── GET /api/events ──────────────────────────────────────────────────────────

async def test_get_events_returns_promoted_task(api_client, conn):
    task_id = await _insert_task(conn, "Calendar task")

    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-01T10:00:00Z",
        "end_time": "2026-05-01T11:00:00Z",
        "title": "Calendar task",
    })

    resp = await api_client.get("/api/events?start=2026-05-01T00:00:00Z&end=2026-05-01T23:59:59Z")
    assert resp.status_code == 200, resp.text
    events = resp.json()
    assert isinstance(events, list)
    ids = [e["id"] for e in events]
    assert task_id in ids


async def test_get_events_empty_outside_range(api_client, conn):
    task_id = await _insert_task(conn, "Out of range task")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-01T10:00:00Z",
        "end_time": "2026-05-01T11:00:00Z",
        "title": "Out of range task",
    })

    resp = await api_client.get("/api/events?start=2026-06-01T00:00:00Z&end=2026-06-30T23:59:59Z")
    assert resp.status_code == 200
    events = resp.json()
    ids = [e["id"] for e in events]
    assert task_id not in ids


# ─── PATCH /api/events/:id ────────────────────────────────────────────────────

async def test_patch_event_moves_time(api_client, conn):
    """Moving a promoted event to a new slot returns the updated CalendarEvent."""
    task_id = await _insert_task(conn, "Movable event")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-02T09:00:00Z",
        "end_time": "2026-05-02T10:00:00Z",
        "title": "Movable event",
    })

    resp = await api_client.patch(f"/api/events/{task_id}", json={
        "start_time": "2026-05-02T14:00:00Z",
        "end_time": "2026-05-02T15:00:00Z",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == task_id
    assert "14:00" in data["start_time"] or "14" in data["start_time"]
    assert "15:00" in data["end_time"] or "15" in data["end_time"]


async def test_patch_event_404_not_an_event(api_client, conn):
    """Patching a task that was never promoted (no start_time) returns 404."""
    task_id = await _insert_task(conn, "Plain task")
    resp = await api_client.patch(f"/api/events/{task_id}", json={
        "start_time": "2026-05-02T14:00:00Z",
        "end_time": "2026-05-02T15:00:00Z",
    })
    assert resp.status_code == 404


async def test_patch_event_404_unknown_id(api_client, conn):
    resp = await api_client.patch("/api/events/00000000-0000-0000-0000-000000000099", json={
        "start_time": "2026-05-02T14:00:00Z",
        "end_time": "2026-05-02T15:00:00Z",
    })
    assert resp.status_code == 404
