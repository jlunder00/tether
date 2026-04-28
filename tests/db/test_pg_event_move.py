"""Tests for update_event_time() scope semantics.

Bug: PATCH /api/events/:id with scope=all only moves the dragged occurrence —
the rest of the series stays at the original time.

Root cause: update_event_time() has no scope parameter; it updates the master
row's start_time to the occurrence's specific date+time, which shifts dtstart
and breaks the series' recurrence schedule.

Fix: add scope='all' support that computes delta = new_start - occurrence_start
and applies it to the master start_time so all occurrences shift by the same
amount without destroying the recurrence anchoring.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone, timedelta

import pytest

from tests.db.pg_conftest import conn, TEST_USER_ID  # noqa: F401
from db.pg_queries.tasks import (
    get_events_for_range,
    update_event_time,
    upsert_task_from_draft,
)
from integrations.models import TaskDraft

pytestmark = pytest.mark.asyncio


async def _insert_recurring_event(conn, start_utc: datetime) -> str:
    """Insert a FREQ=WEEKLY recurring event master. Returns its uuid string."""
    end_utc = start_utc + timedelta(hours=1)
    draft = TaskDraft(
        title="Weekly 9am series",
        source="tether",
        external_id=f"weekly-series-{_uuid.uuid4()}",
        start_time=start_utc,
        end_time=end_utc,
        rrule="RRULE:FREQ=WEEKLY",
    )
    await upsert_task_from_draft(conn, TEST_USER_ID, draft)
    # Fetch back the uuid
    row = await conn.fetchrow(
        "SELECT uuid FROM tasks WHERE external_id = $1",
        draft.external_id,
    )
    return str(row["uuid"])


async def test_update_event_time_scope_all_shifts_all_occurrences(conn):
    """scope='all' must shift every occurrence, not just the dragged one.

    Setup: FREQ=WEEKLY at Mon 2026-05-04 09:00 UTC — 4 occurrences in May.
    Action: drag the second occurrence (May 11 09:00 UTC) to 14:00 UTC.
    Expected: all 4 occurrences appear at 14:00 UTC (not just May 11).
    """
    master_start = datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)
    master_uuid = await _insert_recurring_event(conn, master_start)

    window_start = "2026-05-01T00:00:00Z"
    window_end   = "2026-05-31T23:59:59Z"

    # Confirm 4 occurrences at 09:00 UTC before move
    occs_before = await get_events_for_range(conn, window_start, window_end)
    series_before = [e for e in occs_before if e["id"] == master_uuid]
    assert len(series_before) == 4, f"Expected 4 occurrences, got {len(series_before)}"
    for occ in series_before:
        utc_h = datetime.fromisoformat(occ["start_time"]).astimezone(timezone.utc).hour
        assert utc_h == 9, f"Pre-move: expected UTC hour 9, got {utc_h}"

    # Second occurrence: May 11 09:00 UTC → drag to May 11 14:00 UTC
    second_occ_start = "2026-05-11T09:00:00Z"
    new_start        = "2026-05-11T14:00:00Z"
    new_end          = "2026-05-11T15:00:00Z"

    result = await update_event_time(
        conn, master_uuid, new_start, new_end,
        original_start_time=second_occ_start,
    )
    assert result is not None, "update_event_time(scope='all') returned None"

    # All 4 occurrences must now be at 14:00 UTC
    occs_after = await get_events_for_range(conn, window_start, window_end)
    series_after = [e for e in occs_after if e["id"] == master_uuid]
    assert len(series_after) == 4, (
        f"Expected 4 occurrences after scope=all move, got {len(series_after)}"
    )
    for occ in series_after:
        utc_h = datetime.fromisoformat(occ["start_time"]).astimezone(timezone.utc).hour
        assert utc_h == 14, (
            f"scope=all should shift ALL occurrences to 14:00 UTC; got UTC hour {utc_h} "
            f"for occurrence {occ['start_time']}"
        )


async def test_update_event_time_scope_all_gcal_rrule_shifts_embedded_dtstart(conn):
    """scope=all on a GCal-synced event (rrule has embedded DTSTART;TZID) must
    rewrite the embedded DTSTART so expand_recurring uses the new wall-clock time.

    Regression: before the fix, update_event_time updated tasks.start_time but
    left DTSTART;TZID stale.  rrulestr prefers embedded DTSTART over the dtstart=
    kwarg, so get_events_for_range still returned occurrences at the original time.
    """
    from datetime import timezone as _tz
    from dateutil.rrule import rrulestr

    # Simulate a GCal-synced event: 9am Eastern (winter), stored as 14:00 UTC.
    # The mapping layer embeds DTSTART;TZID= so DST is handled correctly.
    master_start_utc = datetime(2026, 5, 4, 13, 0, tzinfo=_tz.utc)  # 9am EDT
    master_end_utc   = master_start_utc + timedelta(hours=1)
    gcal_rrule = "DTSTART;TZID=America/New_York:20260504T090000\nRRULE:FREQ=WEEKLY"

    draft = TaskDraft(
        title="GCal Eastern 9am",
        source="tether",
        external_id=f"gcal-eastern-{_uuid.uuid4()}",
        start_time=master_start_utc,
        end_time=master_end_utc,
        rrule=gcal_rrule,
    )
    await upsert_task_from_draft(conn, TEST_USER_ID, draft)
    row = await conn.fetchrow(
        "SELECT uuid FROM tasks WHERE external_id = $1", draft.external_id
    )
    master_uuid = str(row["uuid"])

    window = ("2026-05-01T00:00:00Z", "2026-05-31T23:59:59Z")

    # Confirm 4 occurrences at 9am EDT (13:00 UTC) before move
    occs_before = await get_events_for_range(conn, *window)
    series = [e for e in occs_before if e["id"] == master_uuid]
    assert len(series) == 4
    for occ in series:
        utc_h = datetime.fromisoformat(occ["start_time"]).astimezone(_tz.utc).hour
        assert utc_h == 13, f"Pre-move: expected 9am EDT (13:00 UTC), got UTC hour {utc_h}"

    # Drag second occurrence (May 11, 9am EDT) to 2pm EDT
    second_occ_original = "2026-05-11T13:00:00Z"   # 9am EDT
    new_start            = "2026-05-11T18:00:00Z"   # 2pm EDT
    new_end              = "2026-05-11T19:00:00Z"

    result = await update_event_time(
        conn, master_uuid, new_start, new_end,
        original_start_time=second_occ_original,
    )
    assert result is not None

    # All 4 occurrences must now show 2pm EDT (18:00 UTC)
    occs_after = await get_events_for_range(conn, *window)
    series_after = [e for e in occs_after if e["id"] == master_uuid]
    assert len(series_after) == 4
    for occ in series_after:
        utc_h = datetime.fromisoformat(occ["start_time"]).astimezone(_tz.utc).hour
        assert utc_h == 18, (
            f"After scope=all on GCal rrule: expected 2pm EDT (18:00 UTC), "
            f"got UTC hour {utc_h} — DTSTART;TZID was likely not rewritten"
        )

    # Also verify the stored rrule has the updated DTSTART (not the original 9am)
    stored = await conn.fetchrow("SELECT rrule FROM tasks WHERE uuid = $1::uuid", master_uuid)
    assert "T140000" in (stored["rrule"] or ""), (
        f"Stored rrule should have DTSTART at 14:00 (2pm ET); got: {stored['rrule']!r}"
    )


async def test_update_event_time_recurring_without_original_start_raises(conn):
    """Calling update_event_time on a recurring event without original_start_time
    must raise ValueError — the direct UPDATE would corrupt the recurrence anchor.
    """
    master_start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    master_uuid = await _insert_recurring_event(conn, master_start)

    with pytest.raises(ValueError, match="recurring event"):
        await update_event_time(
            conn, master_uuid,
            "2026-06-01T14:00:00Z",
            "2026-06-01T15:00:00Z",
            # no original_start_time — should raise, not silently corrupt
        )


async def test_update_event_time_default_scope_still_works(conn):
    """Existing callers without original_start_time must continue working for
    non-recurring (single) events — the direct UPDATE path is still used.
    """
    # Insert a simple non-recurring event via upsert_task_from_draft
    start = datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc)
    draft = TaskDraft(
        title="One-off event",
        source="tether",
        external_id=f"oneoff-{_uuid.uuid4()}",
        start_time=start,
        end_time=start + timedelta(hours=1),
    )
    await upsert_task_from_draft(conn, TEST_USER_ID, draft)
    row = await conn.fetchrow(
        "SELECT uuid FROM tasks WHERE external_id = $1", draft.external_id
    )
    event_uuid = str(row["uuid"])

    result = await update_event_time(
        conn, event_uuid,
        "2026-05-07T14:00:00Z",
        "2026-05-07T15:00:00Z",
        # No scope argument — must default to current behaviour
    )
    assert result is not None
    utc_h = datetime.fromisoformat(result["start_time"]).astimezone(timezone.utc).hour
    assert utc_h == 14
