"""Mock-based tests for recurrence scope DB functions.

Tests patch_recurring_this() and patch_recurring_this_and_future() without
requiring a live database. Uses AsyncMock to simulate conn.fetchrow/execute.

Scenario: a weekly recurring series master (rrule IS NOT NULL). A user edits
"this occurrence" or "this and future" — the DB must mutate atomically and
return the expected event shape.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from db.pg_queries.tasks import patch_recurring_this, patch_recurring_this_and_future


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MASTER_UUID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_NEW_UUID = uuid.UUID("dddddddd-0000-0000-0000-000000000099")
_USER_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TZ = timezone.utc


def _make_conn(fetchrow_returns: list, execute_side_effect=None):
    """Return a mock asyncpg connection.

    fetchrow_returns: list of dicts returned sequentially by conn.fetchrow().
    """
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow_returns)
    conn.execute = AsyncMock(side_effect=execute_side_effect)

    # transaction() as async context manager
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)

    return conn


def _master_fetchrow():
    """Simulates the master task row returned by the initial SELECT."""
    return {
        "uuid": _MASTER_UUID,
        "text": "Weekly standup",
        "start_time": datetime(2026, 5, 4, 9, 0, tzinfo=_TZ),
        "end_time": datetime(2026, 5, 4, 9, 30, tzinfo=_TZ),
        "source": "google_calendar",
        "external_id": "gcal-series-123",
        "anchor_id": None,
        "rrule": "RRULE:FREQ=WEEKLY",
        "exdates": [],
        "context_subject": "work",
    }


def _standalone_fetchrow():
    """Simulates the new standalone event row returned after INSERT.
    source and external_id are None — user-created exceptions are tether-native
    to avoid the partial unique index on (user_id, source, external_id).
    """
    return {
        "uuid": _NEW_UUID,
        "text": "Weekly standup",
        "start_time": datetime(2026, 5, 11, 14, 0, tzinfo=_TZ),
        "end_time": datetime(2026, 5, 11, 14, 30, tzinfo=_TZ),
        "source": None,
        "external_id": None,
        "anchor_id": None,
        "context_subject": "work",
    }


def _new_master_fetchrow():
    """Simulates the new master event row after this_and_future INSERT.
    source and external_id are None — tether-native to avoid the unique index.
    """
    return {
        "uuid": _NEW_UUID,
        "text": "Weekly standup",
        "start_time": datetime(2026, 5, 11, 14, 0, tzinfo=_TZ),
        "end_time": datetime(2026, 5, 11, 14, 30, tzinfo=_TZ),
        "source": None,
        "external_id": None,
        "anchor_id": None,
        "context_subject": "work",
    }


# ---------------------------------------------------------------------------
# patch_recurring_this tests
# ---------------------------------------------------------------------------

async def test_patch_recurring_this_returns_new_standalone_event():
    """patch_recurring_this creates a standalone event and returns its CalendarEvent."""
    original_start = datetime(2026, 5, 11, 9, 0, tzinfo=_TZ)
    new_start = datetime(2026, 5, 11, 14, 0, tzinfo=_TZ)
    new_end = datetime(2026, 5, 11, 14, 30, tzinfo=_TZ)

    conn = _make_conn(
        fetchrow_returns=[_master_fetchrow(), _standalone_fetchrow()]
    )

    result = await patch_recurring_this(
        conn,
        event_id=str(_MASTER_UUID),
        original_start_time=original_start.isoformat(),
        new_start_time=new_start.isoformat(),
        new_end_time=new_end.isoformat(),
    )

    assert result is not None
    assert result["id"] == str(_NEW_UUID)
    assert "14:00" in result["start_time"] or "14" in result["start_time"]
    assert result["is_recurring"] is False
    assert result["is_occurrence"] is True


async def test_patch_recurring_this_appends_exdate_to_master():
    """patch_recurring_this must call conn.execute with an EXDATE array append."""
    original_start = datetime(2026, 5, 11, 9, 0, tzinfo=_TZ)
    new_start = datetime(2026, 5, 11, 14, 0, tzinfo=_TZ)
    new_end = datetime(2026, 5, 11, 14, 30, tzinfo=_TZ)

    conn = _make_conn(
        fetchrow_returns=[_master_fetchrow(), _standalone_fetchrow()]
    )

    await patch_recurring_this(
        conn,
        event_id=str(_MASTER_UUID),
        original_start_time=original_start.isoformat(),
        new_start_time=new_start.isoformat(),
        new_end_time=new_end.isoformat(),
    )

    # At least one execute call must contain an EXDATE update
    execute_calls = conn.execute.call_args_list
    assert len(execute_calls) >= 1, "Expected at least one execute() for EXDATE append"
    all_sql = " ".join(str(c) for c in execute_calls)
    assert "exdates" in all_sql.lower(), "EXDATE append SQL must reference exdates column"


async def test_patch_recurring_this_returns_none_for_missing_master():
    """patch_recurring_this returns None when master UUID not found."""
    conn = _make_conn(fetchrow_returns=[None])  # no row found

    result = await patch_recurring_this(
        conn,
        event_id=str(uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")),
        original_start_time="2026-05-11T09:00:00+00:00",
        new_start_time="2026-05-11T14:00:00+00:00",
        new_end_time="2026-05-11T14:30:00+00:00",
    )
    assert result is None


async def test_patch_recurring_this_returns_400_for_non_recurring_event():
    """patch_recurring_this raises ValueError when the event has no rrule."""
    non_recurring_row = {**_master_fetchrow(), "rrule": None}
    conn = _make_conn(fetchrow_returns=[non_recurring_row])

    with pytest.raises(ValueError, match="not a recurring"):
        await patch_recurring_this(
            conn,
            event_id=str(_MASTER_UUID),
            original_start_time="2026-05-11T09:00:00+00:00",
            new_start_time="2026-05-11T14:00:00+00:00",
            new_end_time="2026-05-11T14:30:00+00:00",
        )


# ---------------------------------------------------------------------------
# patch_recurring_this_and_future tests
# ---------------------------------------------------------------------------

async def test_patch_recurring_this_and_future_returns_new_master():
    """patch_recurring_this_and_future inserts a new master and returns its event."""
    original_start = datetime(2026, 5, 11, 9, 0, tzinfo=_TZ)
    new_start = datetime(2026, 5, 11, 14, 0, tzinfo=_TZ)
    new_end = datetime(2026, 5, 11, 14, 30, tzinfo=_TZ)

    conn = _make_conn(
        fetchrow_returns=[_master_fetchrow(), _new_master_fetchrow()]
    )

    result = await patch_recurring_this_and_future(
        conn,
        event_id=str(_MASTER_UUID),
        original_start_time=original_start.isoformat(),
        new_start_time=new_start.isoformat(),
        new_end_time=new_end.isoformat(),
    )

    assert result is not None
    assert result["id"] == str(_NEW_UUID)
    assert result["is_recurring"] is True
    assert result["is_occurrence"] is False


async def test_patch_recurring_this_and_future_sets_until_on_master():
    """patch_recurring_this_and_future must update master's rrule with UNTIL."""
    original_start = datetime(2026, 5, 11, 9, 0, tzinfo=_TZ)
    new_start = datetime(2026, 5, 11, 14, 0, tzinfo=_TZ)
    new_end = datetime(2026, 5, 11, 14, 30, tzinfo=_TZ)

    conn = _make_conn(
        fetchrow_returns=[_master_fetchrow(), _new_master_fetchrow()]
    )

    await patch_recurring_this_and_future(
        conn,
        event_id=str(_MASTER_UUID),
        original_start_time=original_start.isoformat(),
        new_start_time=new_start.isoformat(),
        new_end_time=new_end.isoformat(),
    )

    execute_calls = conn.execute.call_args_list
    all_sql = " ".join(str(c) for c in execute_calls)
    assert "rrule" in all_sql.lower(), "Master rrule UNTIL update SQL must reference rrule column"
    assert "UNTIL" in all_sql, "UNTIL clause must appear in the SQL used to truncate the master series"


async def test_patch_recurring_this_and_future_returns_none_for_missing_master():
    """Returns None when master UUID not found."""
    conn = _make_conn(fetchrow_returns=[None])

    result = await patch_recurring_this_and_future(
        conn,
        event_id=str(uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")),
        original_start_time="2026-05-11T09:00:00+00:00",
        new_start_time="2026-05-11T14:00:00+00:00",
        new_end_time="2026-05-11T14:30:00+00:00",
    )
    assert result is None


async def test_patch_recurring_this_and_future_raises_for_non_recurring():
    """Raises ValueError when the event has no rrule (not a recurring master)."""
    non_recurring_row = {**_master_fetchrow(), "rrule": None}
    conn = _make_conn(fetchrow_returns=[non_recurring_row])

    with pytest.raises(ValueError, match="not a recurring"):
        await patch_recurring_this_and_future(
            conn,
            event_id=str(_MASTER_UUID),
            original_start_time="2026-05-11T09:00:00+00:00",
            new_start_time="2026-05-11T14:00:00+00:00",
            new_end_time="2026-05-11T14:30:00+00:00",
        )


# ---------------------------------------------------------------------------
# _rrule_set_until edge case tests
# ---------------------------------------------------------------------------

from db.pg_queries.tasks import _rrule_set_until
from datetime import datetime, timezone


def test_rrule_set_until_basic():
    """Basic weekly RRULE gets UNTIL appended correctly."""
    dt = datetime(2026, 5, 10, 8, 59, 59, tzinfo=timezone.utc)
    result = _rrule_set_until("RRULE:FREQ=WEEKLY", dt)
    assert result == "RRULE:FREQ=WEEKLY;UNTIL=20260510T085959Z"
    assert ";;" not in result
    assert not result.startswith("RRULE:;")


def test_rrule_set_until_replaces_existing_until():
    """Existing UNTIL is replaced, not duplicated."""
    dt = datetime(2026, 5, 10, 8, 59, 59, tzinfo=timezone.utc)
    result = _rrule_set_until("RRULE:FREQ=WEEKLY;UNTIL=20260101T000000Z", dt)
    assert "20260101T000000Z" not in result
    assert "UNTIL=20260510T085959Z" in result
    assert result.count("UNTIL") == 1


def test_rrule_set_until_strips_count():
    """COUNT is removed and replaced with UNTIL."""
    dt = datetime(2026, 5, 10, 8, 59, 59, tzinfo=timezone.utc)
    result = _rrule_set_until("RRULE:FREQ=WEEKLY;COUNT=10", dt)
    assert "COUNT" not in result
    assert "UNTIL=20260510T085959Z" in result


def test_rrule_set_until_no_leading_trailing_semicolons():
    """Output must not have leading or trailing semicolons in the value part."""
    dt = datetime(2026, 5, 10, 8, 59, 59, tzinfo=timezone.utc)
    # A pathological RRULE that is only UNTIL (no FREQ) — after stripping, value is empty
    result = _rrule_set_until("RRULE:UNTIL=20260101T000000Z", dt)
    assert not result.startswith("RRULE:;"), f"Leading semicolon in: {result!r}"
    assert ";;" not in result, f"Double semicolon in: {result!r}"
    assert result.endswith("UNTIL=20260510T085959Z")


def test_rrule_set_until_without_prefix():
    """Works on bare value strings (no RRULE: prefix)."""
    dt = datetime(2026, 5, 10, 8, 59, 59, tzinfo=timezone.utc)
    result = _rrule_set_until("FREQ=WEEKLY", dt)
    assert result == "FREQ=WEEKLY;UNTIL=20260510T085959Z"
