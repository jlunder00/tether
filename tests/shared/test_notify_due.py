"""Tests for shared.notify_due — Redis next-due gating for notification checks.

Covers:
- set_component_due / get_due_user_ids: combined ZSET scoring across components
- is_due: single-user cheap check
- Fail-open behaviour when Redis is unavailable (no server/redis_url/redis_client)
- next_anchor_boundary: pure function computing the next anchor start time
"""
from __future__ import annotations

import time

import fakeredis
import pytest

pytestmark = pytest.mark.timeout(30)


# ---------------------------------------------------------------------------
# set_component_due / get_due_user_ids
# ---------------------------------------------------------------------------

async def test_get_due_user_ids_returns_user_whose_due_time_has_passed():
    from shared.notify_due import get_due_user_ids, set_component_due

    server = fakeredis.FakeServer()
    now = time.time()

    await set_component_due("user-a", "anchor", now - 10, server=server)

    due = await get_due_user_ids(now, server=server)
    assert due == ["user-a"]


async def test_get_due_user_ids_excludes_users_not_yet_due():
    from shared.notify_due import get_due_user_ids, set_component_due

    server = fakeredis.FakeServer()
    now = time.time()

    await set_component_due("user-future", "anchor", now + 3600, server=server)

    due = await get_due_user_ids(now, server=server)
    assert due == []


async def test_get_due_user_ids_returns_empty_list_when_queue_empty():
    from shared.notify_due import get_due_user_ids

    server = fakeredis.FakeServer()
    due = await get_due_user_ids(time.time(), server=server)
    assert due == []


async def test_set_component_due_combines_min_across_components():
    """The combined due_queue score must be the MIN of all known components —
    a user is due as soon as ANY one component (anchor/followup/meeting) is due,
    not only when all of them are."""
    from shared.notify_due import get_due_user_ids, set_component_due

    server = fakeredis.FakeServer()
    now = time.time()

    await set_component_due("user-b", "anchor", now + 100, server=server)
    await set_component_due("user-b", "followup", now + 10, server=server)

    # Not due yet (both components still in the future)
    assert await get_due_user_ids(now, server=server) == []

    # Due once we pass the earlier (followup) component, even though the
    # anchor component is still far in the future.
    assert await get_due_user_ids(now + 15, server=server) == ["user-b"]


async def test_set_component_due_updates_existing_component_independently():
    """Updating one component must not clobber a different component's value —
    the combined score must reflect the min of the freshest values for BOTH."""
    from shared.notify_due import get_due_user_ids, set_component_due

    server = fakeredis.FakeServer()
    now = time.time()

    await set_component_due("user-c", "anchor", now + 50, server=server)
    await set_component_due("user-c", "followup", now + 200, server=server)
    # Push the followup component further out — anchor (50) should still govern.
    await set_component_due("user-c", "followup", now + 300, server=server)

    assert await get_due_user_ids(now + 60, server=server) == ["user-c"]  # anchor passed
    assert await get_due_user_ids(now + 10, server=server) == []  # neither passed yet


async def test_set_component_due_meeting_component_from_premium_contributes():
    """Premium contributes a 'meeting' component to the SAME due_queue — the
    cron's single range query must see meeting-only-due users too."""
    from shared.notify_due import get_due_user_ids, set_component_due

    server = fakeredis.FakeServer()
    now = time.time()

    await set_component_due("user-d", "meeting", now - 1, server=server)

    assert await get_due_user_ids(now, server=server) == ["user-d"]


# ---------------------------------------------------------------------------
# is_due
# ---------------------------------------------------------------------------

async def test_is_due_true_when_combined_score_has_passed():
    from shared.notify_due import is_due, set_component_due

    server = fakeredis.FakeServer()
    now = time.time()
    await set_component_due("user-e", "anchor", now - 5, server=server)

    assert await is_due("user-e", now, server=server) is True


async def test_is_due_false_when_combined_score_in_future():
    from shared.notify_due import is_due, set_component_due

    server = fakeredis.FakeServer()
    now = time.time()
    await set_component_due("user-f", "anchor", now + 3600, server=server)

    assert await is_due("user-f", now, server=server) is False


async def test_is_due_fails_open_true_for_unknown_user():
    """A user never seen before (no cache entry — cold start / new link) must
    be treated as due so their first real check isn't silently skipped."""
    from shared.notify_due import is_due

    server = fakeredis.FakeServer()
    assert await is_due("never-seen-user", time.time(), server=server) is True


# ---------------------------------------------------------------------------
# Fail-open when Redis is unavailable entirely
# ---------------------------------------------------------------------------

async def test_get_due_user_ids_returns_none_when_redis_unavailable(monkeypatch):
    """None is the fail-open sentinel — distinct from an empty list, so callers
    can tell 'confirmed nothing due' apart from 'gating unavailable, do the
    real (unfiltered) check instead.'"""
    from shared import notify_due

    monkeypatch.delenv("REDIS_URL", raising=False)
    result = await notify_due.get_due_user_ids(time.time())
    assert result is None


async def test_is_due_returns_true_when_redis_unavailable(monkeypatch):
    from shared import notify_due

    monkeypatch.delenv("REDIS_URL", raising=False)
    assert await notify_due.is_due("any-user", time.time()) is True


async def test_set_component_due_noop_when_redis_unavailable(monkeypatch):
    """Must not raise — gating is best-effort, never fatal to the caller."""
    from shared import notify_due

    monkeypatch.delenv("REDIS_URL", raising=False)
    await notify_due.set_component_due("any-user", "anchor", time.time())  # no raise


# ---------------------------------------------------------------------------
# Fail-open when Redis IS configured but the call itself raises (timeout,
# connection reset, auth failure) — the case that matters most in production,
# distinct from "REDIS_URL unset" above.
# ---------------------------------------------------------------------------

class _RaisingRedisClient:
    """Stand-in for a configured-but-broken Redis client — every method
    raises, simulating a connection drop/timeout mid-call."""

    async def _boom(self, *args, **kwargs):
        raise ConnectionError("simulated Redis connection failure")

    zrangebyscore = _boom
    zscore = _boom
    hset = _boom
    hgetall = _boom
    expire = _boom
    zadd = _boom
    get = _boom
    set = _boom


async def test_get_due_user_ids_fails_open_when_redis_call_raises():
    from shared.notify_due import get_due_user_ids

    result = await get_due_user_ids(time.time(), redis_client=_RaisingRedisClient())
    assert result is None


async def test_is_due_fails_open_when_redis_call_raises():
    from shared.notify_due import is_due

    result = await is_due("some-user", time.time(), redis_client=_RaisingRedisClient())
    assert result is True


async def test_set_component_due_does_not_raise_when_redis_call_raises():
    from shared.notify_due import set_component_due

    # Must not propagate — best-effort cache write, caller never sees this.
    await set_component_due("some-user", "anchor", time.time(), redis_client=_RaisingRedisClient())


async def test_get_cached_anchors_fails_open_when_redis_call_raises():
    from shared.notify_due import get_cached_anchors

    result = await get_cached_anchors("some-user", redis_client=_RaisingRedisClient())
    assert result is None


async def test_set_cached_anchors_does_not_raise_when_redis_call_raises():
    from shared.notify_due import set_cached_anchors

    await set_cached_anchors("some-user", [{"id": "a"}], redis_client=_RaisingRedisClient())


# ---------------------------------------------------------------------------
# next_anchor_boundary — pure function, no Redis/Postgres involved
# ---------------------------------------------------------------------------

from datetime import datetime  # noqa: E402


def _dt(h, m, *, day=15):
    return datetime(2026, 6, day, h, m)


async def test_next_anchor_boundary_returns_next_start_today():
    from shared.notify_due import next_anchor_boundary

    anchors = [
        {"id": "grind_am", "time": "09:00", "duration_minutes": 60},
        {"id": "grind_pm", "time": "14:00", "duration_minutes": 60},
    ]
    now = _dt(8, 0)
    boundary = next_anchor_boundary(anchors, now)
    assert boundary == _dt(9, 0)


async def test_next_anchor_boundary_returns_active_anchor_end_when_inside_window():
    """While inside an anchor's active window, the next boundary is that
    anchor's END (when is_anchor_active flips false), not its start again."""
    from shared.notify_due import next_anchor_boundary

    anchors = [{"id": "grind_am", "time": "09:00", "duration_minutes": 60}]
    now = _dt(9, 30)
    boundary = next_anchor_boundary(anchors, now)
    assert boundary == _dt(10, 0)


async def test_next_anchor_boundary_wraps_to_tomorrow_after_last_anchor():
    from shared.notify_due import next_anchor_boundary

    anchors = [{"id": "grind_am", "time": "09:00", "duration_minutes": 60}]
    now = _dt(23, 0)
    boundary = next_anchor_boundary(anchors, now)
    assert boundary == _dt(9, 0, day=16)


async def test_next_anchor_boundary_returns_none_when_no_anchors():
    from shared.notify_due import next_anchor_boundary

    assert next_anchor_boundary([], _dt(9, 0)) is None


async def test_next_anchor_boundary_skips_malformed_row_without_crashing():
    """A bad row (missing/garbage 'time') must not take down the computation
    for every other anchor — it's skipped, logged, and the rest still work."""
    from shared.notify_due import next_anchor_boundary

    anchors = [
        {"id": "bad", "time": "not-a-time", "duration_minutes": 30},
        {"id": "missing-time", "duration_minutes": 30},
        {"id": "good", "time": "09:00", "duration_minutes": 30},
    ]
    boundary = next_anchor_boundary(anchors, _dt(8, 0))
    assert boundary == _dt(9, 0)


async def test_next_anchor_boundary_returns_none_when_all_rows_malformed():
    from shared.notify_due import next_anchor_boundary

    anchors = [{"id": "bad", "time": "garbage"}]
    assert next_anchor_boundary(anchors, _dt(8, 0)) is None
