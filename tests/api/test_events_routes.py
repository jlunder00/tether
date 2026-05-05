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
            plan_date, start_time, end_time,
            source, external_id, rrule
        )
        VALUES (
            gen_random_uuid(),
            current_setting('app.current_user_id', true)::uuid,
            'Weekly recurring event',
            'pending',
            '2026-05-04',
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
                           plan_date, start_time, end_time, original_start_time)
        VALUES (
            $1, current_setting('app.current_user_id', true)::uuid,
            'Moved exception', 'pending', 'google_calendar', 'gcal-exc-1',
            $2, '2026-05-11', '2026-05-11T14:00:00Z', '2026-05-11T14:30:00Z', '2026-05-11T09:00:00Z'
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


async def test_delete_scope_this_on_non_recurring_returns_400(api_client, conn):
    """scope=this on a non-recurring event returns 400 — no rrule to append EXDATE to."""
    task_id = await _insert_task(conn, "Non-recurring scope=this target")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-10T09:00:00Z",
        "end_time": "2026-05-10T10:00:00Z",
    })

    resp = await api_client.delete(
        f"/api/events/{task_id}?scope=this&original_start_time=2026-05-10T09:00:00Z"
    )
    assert resp.status_code == 400, (
        f"scope=this on a non-recurring event must return 400, got {resp.status_code}: {resp.text}"
    )


async def test_delete_scope_this_and_future_on_non_recurring_returns_400(api_client, conn):
    """scope=this_and_future on a non-recurring event returns 400 — no rrule to truncate."""
    task_id = await _insert_task(conn, "Non-recurring scope=this_and_future target")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-05-10T09:00:00Z",
        "end_time": "2026-05-10T10:00:00Z",
    })

    resp = await api_client.delete(
        f"/api/events/{task_id}?scope=this_and_future&original_start_time=2026-05-10T09:00:00Z"
    )
    assert resp.status_code == 400, (
        f"scope=this_and_future on a non-recurring event must return 400, got {resp.status_code}: {resp.text}"
    )


async def test_delete_scope_this_repeated_does_not_duplicate_exdate(api_client, conn):
    """Deleting the same occurrence twice via scope=this does not produce duplicate EXDATEs."""
    master_id = await _insert_recurring_master(conn, "RRULE:FREQ=WEEKLY")
    original_start = "2026-05-11T09:00:00Z"

    await api_client.delete(
        f"/api/events/{master_id}?scope=this&original_start_time={original_start}"
    )
    await api_client.delete(
        f"/api/events/{master_id}?scope=this&original_start_time={original_start}"
    )

    row = await conn.fetchrow("SELECT exdates FROM tasks WHERE uuid = $1::uuid", master_id)
    exdates = row["exdates"] or []
    matching = [e for e in exdates if "20260511" in e or "2026-05-11" in e]
    assert len(matching) == 1, (
        f"EXDATE for 2026-05-11 must appear exactly once, got: {exdates}"
    )


# ─── Fix A: promote_task_to_event sets plan_date ──────────────────────────────

async def test_post_event_sets_plan_date(api_client, conn):
    """Promoting a task to a calendar event must set plan_date to the UTC date of start_time."""
    task_id = await _insert_task(conn, "Plan-date promotion test")

    resp = await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-06-15T09:00:00Z",
        "end_time": "2026-06-15T10:00:00Z",
        "title": "Plan-date promotion test",
    })
    assert resp.status_code == 201, resp.text

    row = await conn.fetchrow(
        "SELECT plan_date FROM tasks WHERE uuid = $1::uuid", task_id
    )
    assert row is not None
    assert row["plan_date"] is not None, (
        "promote_task_to_event must set plan_date so the task is visible to /api/plan/range"
    )
    # plan_date should equal the UTC date of start_time
    assert str(row["plan_date"]) == "2026-06-15", (
        f"plan_date should be 2026-06-15, got {row['plan_date']!r}"
    )


# ─── Fix B: promote_task_to_event clears anchor_id ───────────────────────────

async def _insert_task_with_anchor(conn, text: str, anchor_id: str, plan_date: str) -> str:
    """Insert a plan task (with anchor_id) and return its UUID string."""
    row = await conn.fetchrow(
        """
        INSERT INTO tasks (uuid, user_id, text, status, plan_date, anchor_id)
        VALUES (
            gen_random_uuid(),
            current_setting('app.current_user_id', true)::uuid,
            $1, 'pending', $2, $3::uuid
        )
        RETURNING uuid
        """,
        text, plan_date, anchor_id,
    )
    return str(row["uuid"])


async def _ensure_anchor(conn) -> str:
    """Return an existing anchor_id or create one, returning its UUID string."""
    row = await conn.fetchrow(
        "SELECT id FROM anchors WHERE user_id = current_setting('app.current_user_id', true)::uuid LIMIT 1"
    )
    if row:
        return str(row["id"])
    # Create a minimal anchor for testing — id has no DB default, must supply explicitly
    row = await conn.fetchrow(
        """
        INSERT INTO anchors (id, user_id, name, time, duration_minutes)
        VALUES (gen_random_uuid(), current_setting('app.current_user_id', true)::uuid, 'Morning', '09:00', 120)
        RETURNING id
        """
    )
    return str(row["id"])


async def test_post_event_clears_anchor_id(api_client, conn):
    """Promoting a plan task to a calendar event must clear anchor_id (tri-state model)."""
    anchor_id = await _ensure_anchor(conn)
    task_id = await _insert_task_with_anchor(conn, "Plan task to promote", anchor_id, "2026-06-15")

    # Verify the task starts with an anchor_id
    before = await conn.fetchrow("SELECT anchor_id FROM tasks WHERE uuid = $1::uuid", task_id)
    assert before["anchor_id"] is not None, "Pre-condition: task must have anchor_id set"

    resp = await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-06-15T14:00:00Z",
        "end_time": "2026-06-15T15:00:00Z",
        "title": "Plan task to promote",
    })
    assert resp.status_code == 201, resp.text

    row = await conn.fetchrow("SELECT anchor_id FROM tasks WHERE uuid = $1::uuid", task_id)
    assert row["anchor_id"] is None, (
        "promote_task_to_event must clear anchor_id so the task leaves the plan sidebar"
    )


# ─── Fix A: update_event_time updates plan_date when day changes ──────────────

async def test_patch_event_updates_plan_date_on_day_change(api_client, conn):
    """Moving an event to a different day must update plan_date to the new UTC date."""
    task_id = await _insert_task(conn, "Day-change event")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-06-10T09:00:00Z",
        "end_time": "2026-06-10T10:00:00Z",
        "title": "Day-change event",
    })

    # Move to a different day
    resp = await api_client.patch(f"/api/events/{task_id}", json={
        "start_time": "2026-06-11T09:00:00Z",
        "end_time": "2026-06-11T10:00:00Z",
    })
    assert resp.status_code == 200, resp.text

    row = await conn.fetchrow("SELECT plan_date FROM tasks WHERE uuid = $1::uuid", task_id)
    assert row["plan_date"] is not None, "plan_date must remain set after event is moved"
    assert str(row["plan_date"]) == "2026-06-11", (
        f"plan_date must update to new event date 2026-06-11, got {row['plan_date']!r}"
    )


async def test_patch_event_same_day_keeps_plan_date(api_client, conn):
    """Moving an event within the same day must not change plan_date."""
    task_id = await _insert_task(conn, "Same-day move event")
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-06-10T09:00:00Z",
        "end_time": "2026-06-10T10:00:00Z",
        "title": "Same-day move event",
    })

    resp = await api_client.patch(f"/api/events/{task_id}", json={
        "start_time": "2026-06-10T14:00:00Z",
        "end_time": "2026-06-10T15:00:00Z",
    })
    assert resp.status_code == 200, resp.text

    row = await conn.fetchrow("SELECT plan_date FROM tasks WHERE uuid = $1::uuid", task_id)
    assert str(row["plan_date"]) == "2026-06-10", (
        f"plan_date must stay 2026-06-10 for same-day move, got {row['plan_date']!r}"
    )


# ─── Fix C: demote path regression test ──────────────────────────────────────

async def test_demote_event_restores_plan_task_state(api_client, conn):
    """Demoting a calendar event via PATCH /api/tasks/:id must restore anchor_id,
    plan_date, and clear start_time and end_time (verifying Fix C parity)."""
    anchor_id = await _ensure_anchor(conn)
    task_id = await _insert_task(conn, "Demote regression task")

    # Promote to event first
    await api_client.post("/api/events", json={
        "task_id": task_id,
        "start_time": "2026-06-15T14:00:00Z",
        "end_time": "2026-06-15T15:00:00Z",
        "title": "Demote regression task",
    })

    # Demote back to plan task (frontend sends this payload via PATCH /api/tasks/:id)
    resp = await api_client.patch(f"/api/tasks/{task_id}", json={
        "start_time": None,
        "end_time": None,
        "anchor_id": anchor_id,
        "plan_date": "2026-06-15",
    })
    assert resp.status_code == 200, resp.text

    row = await conn.fetchrow(
        "SELECT start_time, end_time, anchor_id, plan_date FROM tasks WHERE uuid = $1::uuid",
        task_id,
    )
    assert row["start_time"] is None, "demote must clear start_time"
    assert row["end_time"] is None, "demote must clear end_time"
    assert row["anchor_id"] is not None, "demote must set anchor_id"
    assert str(row["anchor_id"]) == anchor_id, f"anchor_id should be {anchor_id}"
    assert str(row["plan_date"]) == "2026-06-15", (
        f"plan_date should be 2026-06-15 after demote, got {row['plan_date']!r}"
    )
