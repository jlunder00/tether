"""Tests for the pure followup-due classification used by the Redis next-due
gating scheme (shared/notify_due.py). No database required — classify_followup_row
depends only on (row, config, now).
"""
from __future__ import annotations

from datetime import datetime, timedelta

CONFIG = {
    "pre_ack_interval_min": 10,
    "pre_ack_max_pings": 3,
    "post_ack_interval_min": 15,
    "post_ack_pings": 2,
}

NOW = datetime(2026, 6, 15, 12, 0, 0)


def _row(**overrides) -> dict:
    base = {
        "acknowledged_at": None,
        "sequence_started_at": (NOW - timedelta(minutes=30)).isoformat(),
        "last_ping_at": None,
        "pre_ack_pings_sent": 0,
        "post_ack_pings_sent": 0,
    }
    base.update(overrides)
    return base


def test_pre_ack_not_yet_due_returns_candidate_at_ref_plus_interval():
    from bot.message_handler import classify_followup_row

    row = _row(sequence_started_at=(NOW - timedelta(minutes=2)).isoformat())
    queue, candidate = classify_followup_row(row, CONFIG, NOW)

    assert queue is None
    assert candidate == NOW - timedelta(minutes=2) + timedelta(minutes=10)


def test_pre_ack_due_returns_pre_queue_and_next_candidate_one_interval_out():
    from bot.message_handler import classify_followup_row

    row = _row(sequence_started_at=(NOW - timedelta(minutes=15)).isoformat())
    queue, candidate = classify_followup_row(row, CONFIG, NOW)

    assert queue == "pre"
    assert candidate == NOW + timedelta(minutes=10)


def test_pre_ack_exhausted_pings_returns_no_candidate():
    """Once pre_ack_max_pings is hit, this row contributes no future due time
    (it needs a real acknowledgement to progress, not a timer)."""
    from bot.message_handler import classify_followup_row

    row = _row(
        sequence_started_at=(NOW - timedelta(minutes=100)).isoformat(),
        pre_ack_pings_sent=3,
    )
    queue, candidate = classify_followup_row(row, CONFIG, NOW)

    assert queue is None
    assert candidate is None


def test_post_ack_not_yet_due_returns_candidate_at_ref_plus_interval():
    from bot.message_handler import classify_followup_row

    row = _row(
        acknowledged_at=(NOW - timedelta(minutes=5)).isoformat(),
    )
    queue, candidate = classify_followup_row(row, CONFIG, NOW)

    assert queue is None
    assert candidate == NOW - timedelta(minutes=5) + timedelta(minutes=15)


def test_post_ack_due_returns_post_queue_and_next_candidate():
    from bot.message_handler import classify_followup_row

    row = _row(acknowledged_at=(NOW - timedelta(minutes=20)).isoformat())
    queue, candidate = classify_followup_row(row, CONFIG, NOW)

    assert queue == "post"
    assert candidate == NOW + timedelta(minutes=15)


def test_post_ack_exhausted_pings_returns_no_candidate():
    from bot.message_handler import classify_followup_row

    row = _row(
        acknowledged_at=(NOW - timedelta(minutes=100)).isoformat(),
        post_ack_pings_sent=2,
    )
    queue, candidate = classify_followup_row(row, CONFIG, NOW)

    assert queue is None
    assert candidate is None


def test_last_ping_at_takes_precedence_over_sequence_started_at():
    from bot.message_handler import classify_followup_row

    row = _row(
        sequence_started_at=(NOW - timedelta(minutes=100)).isoformat(),
        last_ping_at=(NOW - timedelta(minutes=1)).isoformat(),
    )
    queue, candidate = classify_followup_row(row, CONFIG, NOW)

    assert queue is None
    assert candidate == NOW - timedelta(minutes=1) + timedelta(minutes=10)


def test_unparsable_timestamp_treated_as_never_pinged_and_due_immediately():
    from bot.message_handler import classify_followup_row

    row = _row(sequence_started_at="not-a-timestamp")
    queue, candidate = classify_followup_row(row, CONFIG, NOW)

    assert queue == "pre"  # minutes_since -> inf -> immediately due
