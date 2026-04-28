"""Tests for assign_event_anchor() — pure function, no DB.

Timezone model:
  - now_utc is tz-aware UTC datetime (the caller's clock).
  - Anchor times are HH:MM in server-local time (Pi local == user local).
  - Event start_time/end_time are UTC ISO strings.

Tests run under TZ=UTC so UTC == local, making time comparisons straightforward.
The tz_utc autouse fixture enforces this so tests are portable regardless of
the host machine's configured timezone.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from db.pg_queries.tasks import assign_event_anchor


@pytest.fixture(autouse=True)
def tz_utc(monkeypatch):
    """Force TZ=UTC so UTC event times equal local anchor window times."""
    monkeypatch.setenv("TZ", "UTC")
    # Reload the C-level timezone cache so astimezone() picks up TZ=UTC.
    import time
    time.tzset()
    yield
    time.tzset()  # restore after test


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _anchors():
    return [
        {"id": "morning", "time": "08:00", "duration_minutes": 60},
        {"id": "midday",  "time": "10:00", "duration_minutes": 90},
        {"id": "evening", "time": "17:00", "duration_minutes": 120},
    ]


def _event(start_h: int, start_m: int = 0, end_h: int = None, end_m: int = 0) -> dict:
    if end_h is None:
        end_h = start_h + 1
    return {
        "start_time": f"2026-05-01T{start_h:02d}:{start_m:02d}:00+00:00",
        "end_time":   f"2026-05-01T{end_h:02d}:{end_m:02d}:00+00:00",
    }


def _now(h: int, m: int = 0) -> datetime:
    return datetime(2026, 5, 1, h, m, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Rule 1 — currently active anchor overlaps event → return it
# ---------------------------------------------------------------------------

def test_rule1_active_anchor_overlaps_event():
    """now=08:30 (inside Morning), event 08:15-08:45 → Morning."""
    event = _event(8, 15, 8, 45)
    result = assign_event_anchor(event, _anchors(), _now(8, 30))
    assert result == "morning", f"Expected 'morning', got {result!r}"


def test_rule1_active_anchor_overlaps_event_midday():
    """now=10:45 (inside Midday), event 10:30-11:00 → Midday."""
    event = _event(10, 30, 11, 0)
    result = assign_event_anchor(event, _anchors(), _now(10, 45))
    assert result == "midday", f"Expected 'midday', got {result!r}"


# ---------------------------------------------------------------------------
# Rule 2 — no active anchor overlaps event, but future anchor will → next upcoming
# ---------------------------------------------------------------------------

def test_rule2_future_anchor_will_overlap():
    """now=09:30 (gap, no active anchor), event 10:15-10:45 → Midday (upcoming)."""
    event = _event(10, 15, 10, 45)
    result = assign_event_anchor(event, _anchors(), _now(9, 30))
    assert result == "midday", f"Expected 'midday', got {result!r}"


def test_rule2_future_anchor_evening():
    """now=11:45 (after Midday, before Evening), event 17:30-18:00 → Evening."""
    event = _event(17, 30, 18, 0)
    result = assign_event_anchor(event, _anchors(), _now(11, 45))
    assert result == "evening", f"Expected 'evening', got {result!r}"


# ---------------------------------------------------------------------------
# Rule 3 — active anchor has moved past event end → return last overlapping
# ---------------------------------------------------------------------------

def test_rule3_active_anchor_past_event_end():
    """now=10:30 (Midday active), event ended at 08:45 → Morning (last overlapping)."""
    event = _event(8, 15, 8, 45)
    result = assign_event_anchor(event, _anchors(), _now(10, 30))
    assert result == "morning", f"Expected 'morning', got {result!r}"


def test_rule3_event_in_gap_all_past():
    """now=17:00 (Evening starts), event was 09:15-09:45 (gap, no anchor overlap).
    No anchor overlapped → fallback to first anchor."""
    event = _event(9, 15, 9, 45)
    result = assign_event_anchor(event, _anchors(), _now(17, 0))
    # Gap event, no anchor overlaps — expect first anchor (rule 5 fallback)
    assert result == "morning", f"Expected 'morning' (fallback), got {result!r}"


# ---------------------------------------------------------------------------
# Rule 4 — before all anchors → return first anchor
# ---------------------------------------------------------------------------

def test_rule4_before_all_anchors():
    """now=07:00 (before first anchor at 08:00) → first anchor 'morning'."""
    event = _event(8, 15, 8, 45)
    result = assign_event_anchor(event, _anchors(), _now(7, 0))
    assert result == "morning", f"Expected 'morning', got {result!r}"


def test_rule4_midnight():
    """now=00:01 → first anchor."""
    event = _event(8, 0, 9, 0)
    result = assign_event_anchor(event, _anchors(), _now(0, 1))
    assert result == "morning"


# ---------------------------------------------------------------------------
# Rule 5 — no anchors overlap event at all → first anchor fallback
# ---------------------------------------------------------------------------

def test_rule5_no_overlap_event_in_gap():
    """Event 09:10-09:50 falls in gap between Morning [08-09) and Midday [10-11:30).
    No anchor overlaps → return first anchor."""
    event = _event(9, 10, 9, 50)
    result = assign_event_anchor(event, _anchors(), _now(9, 15))
    assert result == "morning", f"Expected 'morning' (fallback), got {result!r}"


def test_rule5_no_overlap_late_event_no_future_anchor():
    """Event 20:00-21:00 after all anchors end at 19:00.
    No anchor overlaps, no future anchor → first anchor fallback."""
    event = _event(20, 0, 21, 0)
    result = assign_event_anchor(event, _anchors(), _now(22, 0))
    assert result == "morning", f"Expected 'morning' (fallback), got {result!r}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_anchors_returns_none():
    """No anchors → return None."""
    result = assign_event_anchor(_event(9, 0), [], _now(9, 0))
    assert result is None


def test_single_anchor_always_returns_it():
    """Single anchor → always returned regardless of overlap."""
    anchors = [{"id": "only", "time": "09:00", "duration_minutes": 60}]
    result = assign_event_anchor(_event(14, 0, 15, 0), anchors, _now(14, 0))
    assert result == "only"
