"""Unit tests for RRULE occurrence expansion in event queries.

Tests the expand_recurring() helper and the get_events_with_recurrence()
query function. No live DB needed — all mocked.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

import pytest

from db.pg_queries.tasks import expand_recurring


# ---------------------------------------------------------------------------
# expand_recurring — basic weekly recurrence
# ---------------------------------------------------------------------------

def _make_task(rrule: str, start: datetime, end: datetime, **kwargs) -> dict:
    """Build a minimal recurring task row dict."""
    duration = end - start
    return {
        "id": kwargs.get("id", "uuid-series-1"),
        "title": kwargs.get("title", "Weekly meeting"),
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "rrule": rrule,
        "exdates": kwargs.get("exdates", []),
        "source": "google_calendar",
        "external_id": kwargs.get("external_id", "gcal-series-1"),
        "anchor_id": None,
        "is_recurring": True,
        "is_occurrence": False,
    }


def test_expand_weekly_returns_occurrences_in_window():
    """Weekly RRULE produces one occurrence per week within the window."""
    # Monday 2026-05-04, 09:00 UTC — weekly for 4 weeks
    start = datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 4, 9, 30, tzinfo=timezone.utc)
    task = _make_task("RRULE:FREQ=WEEKLY", start, end)

    window_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)

    occurrences = expand_recurring(task, window_start, window_end)

    # May has weeks starting May 4, 11, 18, 25 — 4 occurrences
    assert len(occurrences) == 4
    for occ in occurrences:
        assert occ["is_occurrence"] is True
        assert occ["is_recurring"] is True


def test_expand_recurring_preserves_duration():
    """Each occurrence has the same duration as the original event."""
    start = datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 4, 10, 30, tzinfo=timezone.utc)  # 90 min
    task = _make_task("RRULE:FREQ=WEEKLY", start, end)

    window_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)

    occurrences = expand_recurring(task, window_start, window_end)
    assert len(occurrences) >= 1

    for occ in occurrences:
        occ_start = datetime.fromisoformat(occ["start_time"])
        occ_end = datetime.fromisoformat(occ["end_time"])
        assert occ_end - occ_start == timedelta(minutes=90)


def test_expand_recurring_no_occurrences_outside_window():
    """An event starting in June produces no occurrences for a May window."""
    start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    task = _make_task("RRULE:FREQ=WEEKLY", start, end)

    window_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)

    occurrences = expand_recurring(task, window_start, window_end)
    assert occurrences == []


def test_expand_recurring_respects_exdates():
    """Occurrences matching exdates are excluded from the result."""
    start = datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 4, 9, 30, tzinfo=timezone.utc)
    # Exclude May 11 occurrence
    exdate = "EXDATE;TZID=UTC:20260511T090000Z"
    task = _make_task("RRULE:FREQ=WEEKLY", start, end, exdates=[exdate])

    window_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)

    occurrences = expand_recurring(task, window_start, window_end)
    occurrence_starts = [occ["start_time"] for occ in occurrences]

    # Should have 3 occurrences (May 4, 18, 25) — May 11 excluded
    assert len(occurrences) == 3
    excluded_dt = datetime(2026, 5, 11, 9, 0, tzinfo=timezone.utc)
    for start_str in occurrence_starts:
        occ_dt = datetime.fromisoformat(start_str)
        assert occ_dt.date() != excluded_dt.date(), "May 11 should be excluded"


def test_expand_recurring_daily_within_window():
    """Daily RRULE within a 3-day window produces 3 occurrences."""
    start = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 1, 8, 15, tzinfo=timezone.utc)
    task = _make_task("RRULE:FREQ=DAILY", start, end)

    window_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 3, 23, 59, 59, tzinfo=timezone.utc)

    occurrences = expand_recurring(task, window_start, window_end)
    assert len(occurrences) == 3


def test_expand_recurring_count_limited_rrule():
    """RRULE with COUNT limits total occurrences."""
    start = datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 4, 9, 30, tzinfo=timezone.utc)
    task = _make_task("RRULE:FREQ=WEEKLY;COUNT=2", start, end)

    # Big window — but COUNT=2 means only 2 occur ever
    window_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc)

    occurrences = expand_recurring(task, window_start, window_end)
    assert len(occurrences) == 2


def test_expand_recurring_comma_separated_exdates():
    """Multiple dates on a single EXDATE line are all excluded (RFC 5545 comma syntax)."""
    start = datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 4, 9, 30, tzinfo=timezone.utc)
    # Single EXDATE line with two comma-separated datetimes: May 11 and May 18
    exdate = "EXDATE;TZID=UTC:20260511T090000Z,20260518T090000Z"
    task = _make_task("RRULE:FREQ=WEEKLY", start, end, exdates=[exdate])

    window_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)

    occurrences = expand_recurring(task, window_start, window_end)

    # 4 weekly occurrences (May 4, 11, 18, 25); May 11 and 18 excluded → 2 remain
    assert len(occurrences) == 2
    occurrence_dates = {datetime.fromisoformat(occ["start_time"]).date() for occ in occurrences}
    from datetime import date
    assert date(2026, 5, 4) in occurrence_dates
    assert date(2026, 5, 25) in occurrence_dates
    assert date(2026, 5, 11) not in occurrence_dates
    assert date(2026, 5, 18) not in occurrence_dates


def test_expand_recurring_naive_window_bounds_with_aware_task():
    """Reproduces production 500: naive window bounds + tz-aware task dtstart.

    The API may receive query params without timezone offset (e.g. "2026-05-01T00:00:00").
    _parse_ts returns a naive datetime. But dtstart comes from asyncpg TIMESTAMPTZ and is
    tz-aware. rrulestr then generates tz-aware datetimes; rule.between(naive, naive) raises
    "can't compare offset-naive and offset-aware datetimes".
    """
    start = datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc)  # tz-aware (from asyncpg)
    end = datetime(2026, 5, 4, 9, 30, tzinfo=timezone.utc)
    task = _make_task("RRULE:FREQ=WEEKLY", start, end)

    # Naive window bounds — what _parse_ts returns for strings like "2026-05-01T00:00:00"
    window_start = datetime(2026, 5, 1)
    window_end = datetime(2026, 5, 31, 23, 59, 59)

    occurrences = expand_recurring(task, window_start, window_end)
    assert len(occurrences) == 4


def test_expand_recurring_naive_dtstart_aware_window_does_not_raise():
    """Inverse case: naive task dtstart + aware window bounds must not raise TypeError.

    Unlikely in production (asyncpg TIMESTAMPTZ always returns tz-aware), but
    the symmetric guard in expand_recurring covers this to prevent a crash if
    a TIMESTAMP column ever returns a naive datetime.
    """
    start = datetime(2026, 5, 4, 9, 0)  # naive — no tzinfo
    end = datetime(2026, 5, 4, 9, 30)
    task = _make_task("RRULE:FREQ=WEEKLY", start, end)

    window_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)

    # Must not raise — returns 4 occurrences (naive rule, bounds stripped to naive)
    occurrences = expand_recurring(task, window_start, window_end)
    assert len(occurrences) == 4


# ---------------------------------------------------------------------------
# DST handling — recurring events must honour wall-clock time after DST change
# ---------------------------------------------------------------------------

def test_recurring_event_from_gcal_expands_correctly_after_dst():
    """A GCal recurring event created in winter must show 9am EDT post-DST.

    Regression for: events fetched from Google Calendar display 1 hour off after DST.

    Root cause (unfixed): map_event stores start_time as UTC and the RRULE without a
    DTSTART;TZID prefix. expand_recurring then anchors weekly expansion at UTC 14:00
    (9am EST), producing 14:00 UTC in summer = 10am EDT — 1 hour late.

    Fix: map_event embeds DTSTART;TZID=America/New_York in the stored rrule so
    expand_recurring uses wall-clock semantics.
    """
    from integrations.google_calendar.mapping import map_event as _map_event

    raw = {
        "id": "gcal-dst-regression",
        "summary": "Weekly 9am Eastern",
        # Winter: 9am EST = 14:00 UTC.  After DST: 9am EDT = 13:00 UTC.
        "start": {"dateTime": "2026-02-09T09:00:00-05:00", "timeZone": "America/New_York"},
        "end":   {"dateTime": "2026-02-09T10:00:00-05:00", "timeZone": "America/New_York"},
        "recurrence": ["RRULE:FREQ=WEEKLY"],
    }
    draft = _map_event(raw)

    task = {
        "id": "uuid-dst-test",
        "title": draft.title,
        "start_time": draft.start_time.isoformat(),
        "end_time": draft.end_time.isoformat(),
        "rrule": draft.rrule,
        "exdates": draft.exdates,
        "source": draft.source,
        "external_id": draft.external_id,
        "anchor_id": None,
        "is_recurring": True,
        "is_occurrence": False,
    }

    # April 6 is well past DST switch (US clocks sprang forward March 8, 2026)
    window_start = datetime(2026, 4, 6, tzinfo=timezone.utc)
    window_end   = datetime(2026, 4, 6, 23, 59, tzinfo=timezone.utc)

    occurrences = expand_recurring(task, window_start, window_end)

    assert len(occurrences) == 1, f"Expected 1 occurrence, got {len(occurrences)}"
    occ_utc = datetime.fromisoformat(occurrences[0]["start_time"]).astimezone(timezone.utc)
    assert occ_utc.hour == 13, (
        f"Expected 9am EDT = 13:00 UTC post-DST; got UTC hour {occ_utc.hour} "
        f"(14 would mean DST not applied — 10am EDT instead of 9am)"
    )


# ---------------------------------------------------------------------------
# _rewrite_dtstart_in_rrule — unit tests for the DTSTART rewriter
# ---------------------------------------------------------------------------

def test_rewrite_dtstart_shifts_wall_clock_time():
    """Applying a +5h delta to DTSTART;TZID rewrites the embedded local time.

    This is the critical fix for the Bug 1 × Bug 2 interaction: dateutil prefers
    embedded DTSTART over the dtstart= kwarg, so scope=all must rewrite the line.
    """
    from datetime import timedelta
    from db.pg_queries.tasks import _rewrite_dtstart_in_rrule

    rrule = "DTSTART;TZID=America/New_York:20260209T090000\nRRULE:FREQ=WEEKLY"
    result = _rewrite_dtstart_in_rrule(rrule, timedelta(hours=5))
    assert "DTSTART;TZID=America/New_York:20260209T140000" in result
    assert "RRULE:FREQ=WEEKLY" in result


def test_rewrite_dtstart_bare_rrule_unchanged():
    """A bare RRULE without embedded DTSTART is returned unchanged (no-op)."""
    from datetime import timedelta
    from db.pg_queries.tasks import _rewrite_dtstart_in_rrule

    rrule = "RRULE:FREQ=WEEKLY"
    assert _rewrite_dtstart_in_rrule(rrule, timedelta(hours=5)) == rrule


def test_rewrite_dtstart_preserves_dst_semantics_after_shift():
    """After rewriting DTSTART, rrulestr expands at the new wall-clock time.

    Regression for: scope=all on a GCal-synced recurring event appeared to
    succeed (update returned) but get_events_for_range still showed original time
    because rrulestr ignored the updated start_time and used the stale DTSTART.
    """
    from datetime import timedelta
    from dateutil.rrule import rrulestr
    from db.pg_queries.tasks import _rewrite_dtstart_in_rrule

    original_rrule = "DTSTART;TZID=America/New_York:20260209T090000\nRRULE:FREQ=WEEKLY"
    # Move from 9am to 2pm (+5h)
    shifted_rrule = _rewrite_dtstart_in_rrule(original_rrule, timedelta(hours=5))

    window_start = datetime(2026, 4, 6, tzinfo=timezone.utc)
    window_end   = datetime(2026, 4, 6, 23, 59, tzinfo=timezone.utc)
    rule = rrulestr(shifted_rrule, ignoretz=False)
    occs = list(rule.between(window_start, window_end, inc=True))

    assert len(occs) == 1
    utc_hour = occs[0].astimezone(timezone.utc).hour
    # 2pm EDT = 18:00 UTC; if still 13:00 UTC the DTSTART was not rewritten
    assert utc_hour == 18, (
        f"Expected 2pm EDT (18:00 UTC) after +5h shift; got UTC hour {utc_hour}"
    )


def test_expand_recurring_all_day_exdate_suppresses_occurrence():
    """EXDATE with bare date token (all-day, no time) suppresses the matching occurrence.

    Google Calendar sends all-day EXDATEs as VALUE=DATE tokens:
      EXDATE;VALUE=DATE:20260511
    These must be parsed and the occurrence for that date must be excluded.
    """
    start = datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 4, 23, 59, 59, tzinfo=timezone.utc)
    exdate = "EXDATE;VALUE=DATE:20260511"
    task = _make_task("RRULE:FREQ=WEEKLY", start, end, exdates=[exdate])

    window_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)

    occurrences = expand_recurring(task, window_start, window_end)

    # 4 weekly occurrences (May 4, 11, 18, 25); May 11 excluded → 3 remain
    assert len(occurrences) == 3
    occurrence_dates = {datetime.fromisoformat(occ["start_time"]).date() for occ in occurrences}
    assert date(2026, 5, 11) not in occurrence_dates, "May 11 all-day EXDATE should be excluded"
