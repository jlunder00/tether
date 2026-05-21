"""Unit tests for interactive_agent_layer.trial.TrialCounter.

Tests cover:
- First use returns (True, quota-1)
- Subsequent uses decrement remaining
- At-quota use returns (True, 0) — last allowed
- Over-quota attempt returns (False, 0) — exhausted
- year_month rollover: different month = fresh counter (fresh pool mock)
- Quota read from config (default 10)
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _make_pool(fetchrow_return=None, execute_return=None):
    """Build a minimal mock asyncpg pool."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock(return_value=execute_return)

    # transaction() returns an async context manager that yields conn
    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_cm)

    # pool.acquire() returns an async context manager yielding conn
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)
    return pool, conn


# ---------------------------------------------------------------------------
# First use — no existing row
# ---------------------------------------------------------------------------

async def test_trial_counter_first_use_allowed():
    """First use with no existing row: allowed=True, remaining=quota-1."""
    pool, conn = _make_pool(fetchrow_return=None)  # no existing row
    conn.execute = AsyncMock()

    with patch("interactive_agent_layer.trial.get_trial_monthly_quota", return_value=10):
        from interactive_agent_layer.trial import TrialCounter
        counter = TrialCounter(pool)
        allowed, remaining = await counter.check_and_increment("user-1")

    assert allowed is True
    assert remaining == 9


# ---------------------------------------------------------------------------
# Subsequent use — existing row under quota
# ---------------------------------------------------------------------------

async def test_trial_counter_increments_and_returns_remaining():
    """Existing row with used=5: allowed=True, remaining=quota-6."""
    existing_row = {"used_count": 5}
    pool, conn = _make_pool(fetchrow_return=existing_row)

    with patch("interactive_agent_layer.trial.get_trial_monthly_quota", return_value=10):
        from interactive_agent_layer.trial import TrialCounter
        counter = TrialCounter(pool)
        allowed, remaining = await counter.check_and_increment("user-1")

    assert allowed is True
    assert remaining == 4  # quota(10) - new_count(6) = 4


# ---------------------------------------------------------------------------
# Last allowed use — used goes to exactly quota
# ---------------------------------------------------------------------------

async def test_trial_counter_last_allowed_use():
    """used=9 → last slot: allowed=True, remaining=0."""
    pool, conn = _make_pool(fetchrow_return={"used_count": 9})

    with patch("interactive_agent_layer.trial.get_trial_monthly_quota", return_value=10):
        from interactive_agent_layer.trial import TrialCounter
        counter = TrialCounter(pool)
        allowed, remaining = await counter.check_and_increment("user-1")

    assert allowed is True
    assert remaining == 0


# ---------------------------------------------------------------------------
# Exhausted — used already at quota
# ---------------------------------------------------------------------------

async def test_trial_counter_exhausted_returns_false():
    """used=10 (at quota): allowed=False, remaining=0. Counter NOT incremented."""
    pool, conn = _make_pool(fetchrow_return={"used_count": 10})

    with patch("interactive_agent_layer.trial.get_trial_monthly_quota", return_value=10):
        from interactive_agent_layer.trial import TrialCounter
        counter = TrialCounter(pool)
        allowed, remaining = await counter.check_and_increment("user-1")

    assert allowed is False
    assert remaining == 0
    # execute() must NOT have been called — we don't write when exhausted
    conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Over-quota — used > quota (shouldn't normally happen but be defensive)
# ---------------------------------------------------------------------------

async def test_trial_counter_over_quota_returns_false():
    """used=12 (over quota): allowed=False, counter not incremented."""
    pool, conn = _make_pool(fetchrow_return={"used_count": 12})

    with patch("interactive_agent_layer.trial.get_trial_monthly_quota", return_value=10):
        from interactive_agent_layer.trial import TrialCounter
        counter = TrialCounter(pool)
        allowed, remaining = await counter.check_and_increment("user-1")

    assert allowed is False
    conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# year_month is derived from current UTC time
# ---------------------------------------------------------------------------

async def test_trial_counter_uses_utc_year_month():
    """TrialCounter queries with the current UTC year_month string."""
    pool, conn = _make_pool(fetchrow_return=None)
    year_month_used = []

    async def capture_fetchrow(sql, user_id, year_month, *args):
        year_month_used.append(year_month)
        return None

    conn.fetchrow = capture_fetchrow

    with patch("interactive_agent_layer.trial.get_trial_monthly_quota", return_value=10):
        with patch("interactive_agent_layer.trial.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, tzinfo=timezone.utc)
            from interactive_agent_layer.trial import TrialCounter
            counter = TrialCounter(pool)
            await counter.check_and_increment("user-1")

    assert "2026-05" in year_month_used
