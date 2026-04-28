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


async def test_update_event_time_default_scope_still_works(conn):
    """Existing callers without scope param must continue working (scope='this' default).

    This is a non-recurring event — default scope updates the single record.
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
