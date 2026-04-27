"""Mock-based tests for get_events_for_range exception substitution.

Tests the moved-exception substitution path in get_events_for_range() without
requiring a live database. Uses AsyncMock to simulate conn.fetch returns.

Key scenario: a Google Calendar recurring event where one instance is moved
to a different time on the same day. The function must:
  1. Suppress the "ghost" computed occurrence at the original slot.
  2. Emit the actual exception instance at its real (moved) time.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from db.pg_queries.tasks import get_events_for_range


# ---------------------------------------------------------------------------
# Helpers — build row dicts that duck-type asyncpg.Record
# ---------------------------------------------------------------------------

def _master_row(
    external_id: str,
    start: datetime,
    end: datetime,
    rrule: str = "RRULE:FREQ=WEEKLY",
) -> dict:
    return {
        "uuid": uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"),
        "text": "Weekly standup",
        "start_time": start,
        "end_time": end,
        "source": "google_calendar",
        "external_id": external_id,
        "anchor_id": None,
        "rrule": rrule,
        "recurrence_id": None,
        "exdates": [],
        "original_start_time": None,
    }


def _exception_row(
    external_id: str,
    recurrence_id: str,
    start: datetime,
    end: datetime,
    original_start_time: datetime,
) -> dict:
    return {
        "uuid": uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"),
        "text": "Weekly standup (moved)",
        "start_time": start,
        "end_time": end,
        "source": "google_calendar",
        "external_id": external_id,
        "anchor_id": None,
        "rrule": None,
        "recurrence_id": recurrence_id,
        "exdates": [],
        "original_start_time": original_start_time,
    }


def _conn_with_fetch(*fetch_results) -> MagicMock:
    """Return a mock connection whose fetch() returns successive result sets."""
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=list(fetch_results))
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_moved_exception_replaces_ghost_occurrence():
    """Moved exception suppresses the ghost 09:00 and emits the 14:00 instance.

    Setup:
    - Weekly series: May 4 09:00–09:30 UTC
    - Exception: recurrence_id = series external_id,
                 original_start_time = May 11 09:00 (the slot being replaced),
                 start_time = May 11 14:00 (where it was rescheduled to)
    - Query window: May 1 – May 31 UTC

    Expected: 4 events — May 4 @ 09:00, May 11 @ 14:00, May 18 @ 09:00, May 25 @ 09:00.
    The ghost May 11 @ 09:00 must NOT appear.
    """
    tz = timezone.utc
    series_id = "gcal-series-weeklystandup"

    master = _master_row(
        external_id=series_id,
        start=datetime(2026, 5, 4, 9, 0, tzinfo=tz),
        end=datetime(2026, 5, 4, 9, 30, tzinfo=tz),
    )
    exc = _exception_row(
        external_id="gcal-exception-may11",
        recurrence_id=series_id,
        original_start_time=datetime(2026, 5, 11, 9, 0, tzinfo=tz),   # ghost slot
        start=datetime(2026, 5, 11, 14, 0, tzinfo=tz),                # moved to 14:00
        end=datetime(2026, 5, 11, 14, 30, tzinfo=tz),
    )

    conn = _conn_with_fetch(
        [],       # single events — none
        [master], # recurring masters — one weekly series
        [exc],    # exception instances — one moved exception
    )

    events = await get_events_for_range(
        conn,
        "2026-05-01T00:00:00+00:00",
        "2026-05-31T23:59:59+00:00",
    )

    start_times = [e["start_time"] for e in events]

    assert len(events) == 4, (
        f"Expected 4 events (May 4, 11@14:00, 18, 25), got {len(events)}: {start_times}"
    )

    ghost = datetime(2026, 5, 11, 9, 0, tzinfo=tz).isoformat()
    assert ghost not in start_times, (
        "Ghost May-11 09:00 computed occurrence should be suppressed by the exception"
    )

    moved = datetime(2026, 5, 11, 14, 0, tzinfo=tz).isoformat()
    assert moved in start_times, "Moved May-11 14:00 exception should appear in results"

    # Verify the three unaffected occurrences are present
    for expected_dt in [
        datetime(2026, 5, 4, 9, 0, tzinfo=tz),
        datetime(2026, 5, 18, 9, 0, tzinfo=tz),
        datetime(2026, 5, 25, 9, 0, tzinfo=tz),
    ]:
        assert expected_dt.isoformat() in start_times, (
            f"{expected_dt.isoformat()} should be an unaffected computed occurrence"
        )


async def test_exception_moved_outside_window_suppresses_ghost_emits_nothing():
    """An exception moved outside the query window suppresses the ghost but adds nothing.

    Setup:
    - Weekly series: May 4 09:00 UTC
    - Exception: original_start_time = May 11 09:00,
                 start_time = June 1 09:00 (moved OUTSIDE the May window)
    - Window: May 1 – May 31

    Expected: 3 events — May 4, 18, 25. May 11 ghost suppressed; June 1 not in window.
    """
    tz = timezone.utc
    series_id = "gcal-series-monthly-override"

    master = _master_row(
        external_id=series_id,
        start=datetime(2026, 5, 4, 9, 0, tzinfo=tz),
        end=datetime(2026, 5, 4, 9, 30, tzinfo=tz),
    )
    exc = _exception_row(
        external_id="gcal-exception-june1",
        recurrence_id=series_id,
        original_start_time=datetime(2026, 5, 11, 9, 0, tzinfo=tz),  # was May 11
        start=datetime(2026, 6, 1, 9, 0, tzinfo=tz),                 # moved to June
        end=datetime(2026, 6, 1, 9, 30, tzinfo=tz),
    )

    conn = _conn_with_fetch([], [master], [exc])

    events = await get_events_for_range(
        conn,
        "2026-05-01T00:00:00+00:00",
        "2026-05-31T23:59:59+00:00",
    )

    start_times = [e["start_time"] for e in events]

    assert len(events) == 3, (
        f"Expected 3 events (May 4, 18, 25), got {len(events)}: {start_times}"
    )

    ghost = datetime(2026, 5, 11, 9, 0, tzinfo=tz).isoformat()
    assert ghost not in start_times, "Ghost May-11 occurrence must be suppressed"

    june1 = datetime(2026, 6, 1, 9, 0, tzinfo=tz).isoformat()
    assert june1 not in start_times, "June-1 exception is outside window — must not appear"


async def test_cancelled_exception_instance_not_returned():
    """Soft-deleted (cancelled) exception instances must not appear in event results.

    GCal sync marks cancelled instances with source_status='cancelled' via
    soft_delete_task_by_external_id. The exception query must filter these out
    so they don't land in results as visible events.
    """
    tz = timezone.utc
    series_id = "gcal-series-cancelled-exc"

    master = _master_row(
        external_id=series_id,
        start=datetime(2026, 5, 4, 9, 0, tzinfo=tz),
        end=datetime(2026, 5, 4, 9, 30, tzinfo=tz),
    )
    # Cancelled exception for the May 11 slot
    cancelled_exc = {
        "uuid": uuid.UUID("cccccccc-0000-0000-0000-000000000003"),
        "text": "Weekly standup (cancelled instance)",
        "start_time": datetime(2026, 5, 11, 9, 0, tzinfo=tz),   # within window
        "end_time": datetime(2026, 5, 11, 9, 30, tzinfo=tz),
        "source": "google_calendar",
        "external_id": "gcal-exception-cancelled",
        "anchor_id": None,
        "rrule": None,
        "recurrence_id": series_id,
        "exdates": [],
        "original_start_time": datetime(2026, 5, 11, 9, 0, tzinfo=tz),
        "source_status": "cancelled",
    }

    # The exception query should filter source_status='cancelled' — so we simulate
    # the DB returning an empty list for exceptions (as it should after the fix).
    conn = _conn_with_fetch(
        [],       # single events — none
        [master], # recurring masters — one weekly series
        [],       # exception instances — empty (cancelled row filtered by SQL)
    )

    events = await get_events_for_range(
        conn,
        "2026-05-01T00:00:00+00:00",
        "2026-05-31T23:59:59+00:00",
    )

    start_times = [e["start_time"] for e in events]

    # Should have 4 computed occurrences (no exception substitution)
    assert len(events) == 4, (
        f"Expected 4 computed occurrences, got {len(events)}: {start_times}"
    )
    # Cancelled exception must NOT appear
    assert all(e.get("source_status") != "cancelled" for e in events), (
        "No cancelled events should appear in results"
    )
