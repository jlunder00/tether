"""Tests for CoalescingBuffer."""
from __future__ import annotations

import pytest

from interactive_agent_layer.coalescing import CoalescingBuffer


def make_clock(start: float = 0.0) -> list[float]:
    return [start]


def test_first_call_returns_new_action_id_not_coalesced():
    clock = make_clock()
    buf = CoalescingBuffer(window_seconds=5.0, time_fn=lambda: clock[0])

    action_id, coalesced = buf.record("get_anchors", "Reading your schedule")

    assert isinstance(action_id, str)
    assert len(action_id) > 0
    assert coalesced is False


def test_second_call_within_window_returns_same_id_coalesced():
    clock = make_clock()
    buf = CoalescingBuffer(window_seconds=5.0, time_fn=lambda: clock[0])

    id1, coalesced1 = buf.record("get_anchors", "Reading your schedule")
    assert not coalesced1

    clock[0] = 3.0  # still within 5s window
    id2, coalesced2 = buf.record("get_anchors", "Reading your schedule")

    assert coalesced2 is True
    assert id2 == id1


def test_same_key_after_window_expires_returns_new_id():
    clock = make_clock()
    buf = CoalescingBuffer(window_seconds=5.0, time_fn=lambda: clock[0])

    id1, _ = buf.record("get_anchors", "Reading your schedule")

    clock[0] = 5.0  # exactly at window boundary — NOT within window (< not <=)
    id2, coalesced2 = buf.record("get_anchors", "Reading your schedule")

    assert coalesced2 is False
    assert id2 != id1


def test_different_tool_name_same_phrase_not_coalesced():
    clock = make_clock()
    buf = CoalescingBuffer(window_seconds=5.0, time_fn=lambda: clock[0])

    id1, c1 = buf.record("get_anchors", "Reading your schedule")
    id2, c2 = buf.record("get_tasks", "Reading your schedule")

    assert c1 is False
    assert c2 is False
    assert id1 != id2


def test_same_tool_name_different_phrase_not_coalesced():
    clock = make_clock()
    buf = CoalescingBuffer(window_seconds=5.0, time_fn=lambda: clock[0])

    id1, c1 = buf.record("get_anchors", "Reading your schedule")
    id2, c2 = buf.record("get_anchors", "Fetching data")

    assert c1 is False
    assert c2 is False
    assert id1 != id2


def test_multiple_keys_tracked_independently():
    clock = make_clock()
    buf = CoalescingBuffer(window_seconds=5.0, time_fn=lambda: clock[0])

    id_a1, _ = buf.record("tool_a", "phrase_a")
    id_b1, _ = buf.record("tool_b", "phrase_b")

    clock[0] = 2.0
    id_a2, c_a = buf.record("tool_a", "phrase_a")
    id_b2, c_b = buf.record("tool_b", "phrase_b")

    assert c_a is True
    assert c_b is True
    assert id_a2 == id_a1
    assert id_b2 == id_b1
    assert id_a1 != id_b1


def test_evict_expired_removes_old_leaves_fresh():
    clock = make_clock()
    buf = CoalescingBuffer(window_seconds=5.0, time_fn=lambda: clock[0])

    buf.record("old_tool", "old phrase")   # at t=0
    clock[0] = 3.0
    buf.record("fresh_tool", "fresh phrase")  # at t=3, still within window at t=5

    clock[0] = 5.0  # old_tool entry is now expired (5 - 0 >= 5)
    buf.evict_expired()

    # old_tool should be gone: next call gets a new id, not coalesced
    id_old_new, c_old = buf.record("old_tool", "old phrase")
    assert c_old is False

    # fresh_tool should still be in cache (5 - 3 = 2 < 5)
    clock[0] = 6.0  # 6 - 3 = 3 < 5, still fresh
    id_fresh2, c_fresh = buf.record("fresh_tool", "fresh phrase")
    assert c_fresh is True


def test_window_extension_third_call_still_coalesced():
    """Second call within window resets the clock; third call uses the extended window."""
    clock = make_clock()
    buf = CoalescingBuffer(window_seconds=5.0, time_fn=lambda: clock[0])

    id1, _ = buf.record("get_anchors", "Reading")  # t=0

    clock[0] = 3.0
    id2, c2 = buf.record("get_anchors", "Reading")  # t=3, extends window to t=8
    assert c2 is True
    assert id2 == id1

    clock[0] = 6.0  # t=6, within extended window (3+5=8)
    id3, c3 = buf.record("get_anchors", "Reading")
    assert c3 is True
    assert id3 == id1


def test_evict_expired_called_on_record():
    """Expired entries are purged automatically when record() is called."""
    clock = make_clock()
    buf = CoalescingBuffer(window_seconds=5.0, time_fn=lambda: clock[0])

    buf.record("old_tool", "old phrase")   # t=0, adds entry
    clock[0] = 5.0  # old_tool is now expired (5 - 0 >= 5)

    # Trigger eviction via record() on a DIFFERENT key
    buf.record("new_tool", "new phrase")

    # old_tool must have been evicted during the record() call above
    assert ("old_tool", "old phrase") not in buf._cache, (
        "record() should call evict_expired(), removing stale entries"
    )


def test_injectable_clock_fully_deterministic():
    """Verify no real time.monotonic is used when time_fn is provided."""
    calls = []

    def fake_clock():
        # Always returns 0.0 the first time, 1.0 the second, etc.
        t = float(len(calls))
        calls.append(t)
        return t

    buf = CoalescingBuffer(window_seconds=5.0, time_fn=fake_clock)

    id1, c1 = buf.record("tool", "phrase")  # clock returns 0.0
    id2, c2 = buf.record("tool", "phrase")  # clock returns 1.0 (within 5s)

    assert c1 is False
    assert c2 is True
    assert id2 == id1
    # Confirm our fake clock was actually called
    assert len(calls) >= 2
