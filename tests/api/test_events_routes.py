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


# ─── PATCH /api/events/:id — recurrence scope ────────────────────────────────

async def test_patch_event_scope_all_is_default_behavior(api_client, conn):
    """scope='all' (or absent) updates the master task's time slot."""
    task_id = await _insert_task(conn, "Scope all event")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-02T09:00:00Z",
        "end_time": "2026-05-02T10:00:00Z",
        "title": "Scope all event",
    })

    resp = await api_client.patch(f"/api/events/{task_id}", json={
        "start_time": "2026-05-02T14:00:00Z",
        "end_time": "2026-05-02T15:00:00Z",
        "scope": "all",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == task_id


async def test_patch_event_scope_this_requires_original_start_time(api_client, conn):
    """scope='this' without original_start_time returns 422."""
    task_id = await _insert_task(conn, "Recurring scope test")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-02T09:00:00Z",
        "end_time": "2026-05-02T10:00:00Z",
        "title": "Recurring scope test",
    })

    resp = await api_client.patch(f"/api/events/{task_id}", json={
        "start_time": "2026-05-02T14:00:00Z",
        "end_time": "2026-05-02T15:00:00Z",
        "scope": "this",
        # original_start_time intentionally omitted
    })
    assert resp.status_code == 422, (
        f"scope='this' without original_start_time should be 422, got {resp.status_code}: {resp.text}"
    )


async def test_patch_event_scope_this_and_future_requires_original_start_time(api_client, conn):
    """scope='this_and_future' without original_start_time returns 422."""
    task_id = await _insert_task(conn, "Scope future test")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-02T09:00:00Z",
        "end_time": "2026-05-02T10:00:00Z",
        "title": "Scope future test",
    })

    resp = await api_client.patch(f"/api/events/{task_id}", json={
        "start_time": "2026-05-02T14:00:00Z",
        "end_time": "2026-05-02T15:00:00Z",
        "scope": "this_and_future",
        # original_start_time intentionally omitted
    })
    assert resp.status_code == 422, (
        f"scope='this_and_future' without original_start_time should be 422, got {resp.status_code}: {resp.text}"
    )


async def test_patch_event_scope_invalid_value_returns_422(api_client, conn):
    """An unknown scope value returns 422."""
    task_id = await _insert_task(conn, "Bad scope test")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-02T09:00:00Z",
        "end_time": "2026-05-02T10:00:00Z",
        "title": "Bad scope test",
    })

    resp = await api_client.patch(f"/api/events/{task_id}", json={
        "start_time": "2026-05-02T14:00:00Z",
        "end_time": "2026-05-02T15:00:00Z",
        "scope": "bogus",
    })
    assert resp.status_code == 422


async def test_post_event_context_subject_in_response(api_client, conn):
    """POST /api/events response includes context_subject from the underlying task."""
    # Insert a task with a context_subject
    row = await conn.fetchrow(
        """
        INSERT INTO tasks (uuid, user_id, text, status, context_subject)
        VALUES (
            gen_random_uuid(),
            current_setting('app.current_user_id', true)::uuid,
            'Context-tagged task',
            'pending',
            'work'
        )
        RETURNING uuid
        """,
    )
    task_id = str(row["uuid"])

    resp = await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-10T09:00:00Z",
        "end_time": "2026-05-10T10:00:00Z",
        "title": "Context-tagged task",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data.get("context_subject") == "work", (
        f"promote_task_to_event must return context_subject, got: {data.get('context_subject')!r}"
    )


async def test_patch_event_scope_all_context_subject_in_response(api_client, conn):
    """PATCH /api/events/:id (scope=all) response includes context_subject."""
    row = await conn.fetchrow(
        """
        INSERT INTO tasks (uuid, user_id, text, status, context_subject)
        VALUES (
            gen_random_uuid(),
            current_setting('app.current_user_id', true)::uuid,
            'Context move test',
            'pending',
            'personal'
        )
        RETURNING uuid
        """,
    )
    task_id = str(row["uuid"])

    # Promote to event first
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-10T09:00:00Z",
        "end_time": "2026-05-10T10:00:00Z",
        "title": "Context move test",
    })

    resp = await api_client.patch(f"/api/events/{task_id}", json={
        "start_time": "2026-05-10T14:00:00Z",
        "end_time": "2026-05-10T15:00:00Z",
        "scope": "all",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("context_subject") == "personal", (
        f"update_event_time must return context_subject, got: {data.get('context_subject')!r}"
    )


# ─── DELETE /api/events/:id ──────────────────────────────────────────────────

async def _insert_recurring_master(conn, rrule: str = "RRULE:FREQ=WEEKLY") -> str:
    """Insert a recurring master task (promoted event) and return its UUID string."""
    row = await conn.fetchrow(
        """
        INSERT INTO tasks (
            uuid, user_id, text, status,
            start_time, end_time,
            source, external_id, rrule
        )
        VALUES (
            gen_random_uuid(),
            current_setting('app.current_user_id', true)::uuid,
            'Weekly recurring event',
            'pending',
            '2026-05-04T09:00:00Z',
            '2026-05-04T09:30:00Z',
            'google_calendar',
            'gcal-master-test',
            $1
        )
        RETURNING uuid
        """,
        rrule,
    )
    return str(row["uuid"])


async def test_delete_event_scope_all_removes_task(api_client, conn):
    """DELETE scope=all removes the master task row entirely."""
    task_id = await _insert_task(conn, "Non-recurring single event")
    # Promote it to an event first
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-10T09:00:00Z",
        "end_time": "2026-05-10T10:00:00Z",
    })

    resp = await api_client.delete(f"/api/events/{task_id}?scope=all")
    assert resp.status_code == 204, resp.text

    # Verify task is gone
    row = await conn.fetchrow("SELECT uuid FROM tasks WHERE uuid = $1::uuid", task_id)
    assert row is None, "scope=all must delete the task row"


async def test_delete_event_scope_all_removes_recurring_master_and_exceptions(api_client, conn):
    """DELETE scope=all on a recurring master also deletes orphan exception rows."""
    import uuid
    master_id = await _insert_recurring_master(conn)

    # Insert an exception row linked to this master via recurrence_id
    master_external_id = "gcal-master-test"
    await conn.execute(
        """
        INSERT INTO tasks (uuid, user_id, text, status, source, external_id, recurrence_id,
                           start_time, end_time, original_start_time)
        VALUES (
            $1, current_setting('app.current_user_id', true)::uuid,
            'Moved exception', 'pending', 'google_calendar', 'gcal-exc-1',
            $2, '2026-05-11T14:00:00Z', '2026-05-11T14:30:00Z', '2026-05-11T09:00:00Z'
        )
        """,
        uuid.uuid4(), master_external_id,
    )

    resp = await api_client.delete(f"/api/events/{master_id}?scope=all")
    assert resp.status_code == 204, resp.text

    # Both master and exception must be gone
    master_row = await conn.fetchrow("SELECT uuid FROM tasks WHERE uuid = $1::uuid", master_id)
    assert master_row is None, "Master must be deleted"

    exc_rows = await conn.fetch(
        "SELECT uuid FROM tasks WHERE recurrence_id = $1", master_external_id
    )
    assert len(exc_rows) == 0, "Orphan exceptions must be deleted with master"


async def test_delete_event_scope_this_adds_exdate(api_client, conn):
    """DELETE scope=this adds an EXDATE to the master's rrule, suppressing that occurrence."""
    master_id = await _insert_recurring_master(conn, "RRULE:FREQ=WEEKLY")
    original_start = "2026-05-11T09:00:00Z"

    resp = await api_client.delete(
        f"/api/events/{master_id}?scope=this&original_start_time={original_start}"
    )
    assert resp.status_code == 204, resp.text

    row = await conn.fetchrow("SELECT exdates FROM tasks WHERE uuid = $1::uuid", master_id)
    assert row is not None, "Master task must still exist after scope=this delete"
    exdates = row["exdates"] or []
    assert any("20260511" in e or "2026-05-11" in e for e in exdates), (
        f"EXDATE for 2026-05-11 must be appended; got: {exdates}"
    )


async def test_delete_event_scope_this_and_future_sets_until(api_client, conn):
    """DELETE scope=this_and_future truncates the series by setting UNTIL on the rrule."""
    master_id = await _insert_recurring_master(conn, "RRULE:FREQ=WEEKLY")
    original_start = "2026-05-11T09:00:00Z"

    resp = await api_client.delete(
        f"/api/events/{master_id}?scope=this_and_future&original_start_time={original_start}"
    )
    assert resp.status_code == 204, resp.text

    row = await conn.fetchrow("SELECT rrule FROM tasks WHERE uuid = $1::uuid", master_id)
    assert row is not None, "Master task must still exist after scope=this_and_future delete"
    assert "UNTIL=" in (row["rrule"] or ""), (
        f"UNTIL must be set on rrule to truncate series; got: {row['rrule']!r}"
    )


async def test_delete_event_scope_this_requires_original_start_time(api_client, conn):
    """DELETE scope=this without original_start_time returns 422."""
    task_id = await _insert_task(conn, "Scope this requires original")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-10T09:00:00Z",
        "end_time": "2026-05-10T10:00:00Z",
    })

    resp = await api_client.delete(f"/api/events/{task_id}?scope=this")
    assert resp.status_code == 422, (
        f"scope=this without original_start_time should return 422, got {resp.status_code}"
    )


async def test_delete_event_404_unknown_id(api_client):
    """DELETE unknown event ID returns 404."""
    resp = await api_client.delete(
        "/api/events/00000000-0000-0000-0000-000000000099?scope=all"
    )
    assert resp.status_code == 404


async def test_delete_event_scope_all_default_when_omitted(api_client, conn):
    """DELETE with no scope param defaults to scope=all."""
    task_id = await _insert_task(conn, "Default scope delete")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-10T09:00:00Z",
        "end_time": "2026-05-10T10:00:00Z",
    })

    resp = await api_client.delete(f"/api/events/{task_id}")
    assert resp.status_code == 204, resp.text
