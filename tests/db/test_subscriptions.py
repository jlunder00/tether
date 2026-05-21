"""Unit tests for db.pg_queries.subscriptions.get_user_is_paid_by_id.

Uses mock asyncpg connections — no real DB required.

Tests cover:
- No subscription row → False
- Active premium plan → True
- Active free plan → False
- Cancelled premium → False (status must be 'active')
- SET LOCAL is called with the correct user_id (RLS consistency)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call


def _make_conn(fetchval_return=None):
    """Build a minimal mock asyncpg connection for subscriptions queries."""
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=fetchval_return)
    conn.execute = AsyncMock()

    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_cm)
    return conn


# ---------------------------------------------------------------------------
# No subscription row
# ---------------------------------------------------------------------------

async def test_get_user_is_paid_by_id_no_row_returns_false():
    """No subscription row → False (free tier)."""
    conn = _make_conn(fetchval_return=None)

    from db.pg_queries import get_user_is_paid_by_id
    result = await get_user_is_paid_by_id(conn, "user-abc")

    assert result is False


# ---------------------------------------------------------------------------
# Active premium plan
# ---------------------------------------------------------------------------

async def test_get_user_is_paid_by_id_premium_active_returns_true():
    """Active subscription with plan='premium' → True."""
    conn = _make_conn(fetchval_return="premium")

    from db.pg_queries import get_user_is_paid_by_id
    result = await get_user_is_paid_by_id(conn, "user-abc")

    assert result is True


# ---------------------------------------------------------------------------
# Active free plan
# ---------------------------------------------------------------------------

async def test_get_user_is_paid_by_id_free_plan_returns_false():
    """Active subscription with plan='free' → False."""
    conn = _make_conn(fetchval_return="free")

    from db.pg_queries import get_user_is_paid_by_id
    result = await get_user_is_paid_by_id(conn, "user-abc")

    assert result is False


# ---------------------------------------------------------------------------
# Cancelled premium (status != 'active' filtered in SQL)
# ---------------------------------------------------------------------------

async def test_get_user_is_paid_by_id_cancelled_returns_false():
    """Cancelled subscription: SQL filters status='active', fetchval returns None → False."""
    # The SQL already filters status='active'; cancelled rows don't appear.
    conn = _make_conn(fetchval_return=None)

    from db.pg_queries import get_user_is_paid_by_id
    result = await get_user_is_paid_by_id(conn, "user-abc")

    assert result is False


# ---------------------------------------------------------------------------
# SET LOCAL is called with the correct user_id
# ---------------------------------------------------------------------------

async def test_get_user_is_paid_by_id_sets_rls_context():
    """SET LOCAL app.current_user_id is called with the given user_id."""
    conn = _make_conn(fetchval_return="premium")

    from db.pg_queries import get_user_is_paid_by_id
    await get_user_is_paid_by_id(conn, "user-xyz")

    conn.execute.assert_called_once_with(
        "SET LOCAL app.current_user_id = $1", "user-xyz"
    )
