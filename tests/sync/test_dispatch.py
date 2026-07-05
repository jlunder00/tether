"""Tests for sync/dispatch.py — the live PG NOTIFY dispatch used by
api/routes/integrations.py (manual sync trigger + initial_sync_and_register).

Relocated from the now-deleted tests/sync/test_worker.py when the standalone
LISTEN-loop worker was removed (PR #474); sync/dispatch.py itself is still
live and imported directly by api/routes/integrations.py.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from sync.dispatch import dispatch_sync


def _make_pool():
    """Return a minimal mock pool (dispatch_sync only forwards it to pg.get_conn)."""
    return MagicMock()


def _patch_get_conn(mock_conn):
    """Patch pg.get_conn to yield *mock_conn* as an async context manager."""
    @asynccontextmanager
    async def _fake_get_conn(pool, user_id=None):
        yield mock_conn

    return patch("db.postgres.get_conn", _fake_get_conn)


async def test_dispatch_sync_issues_pg_notify():
    """dispatch_sync calls pg_notify with properly encoded JSON."""
    mock_conn = AsyncMock()
    pool = _make_pool()

    with _patch_get_conn(mock_conn):
        await dispatch_sync(pool, "int-1", "cal-1", provider="google_calendar")

    mock_conn.execute.assert_awaited_once()
    sql, raw_payload = mock_conn.execute.call_args.args
    assert "pg_notify" in sql
    data = json.loads(raw_payload)
    assert data["integration_id"] == "int-1"
    assert data["calendar_id"] == "cal-1"
    assert data["provider"] == "google_calendar"
    assert data["type"] == "poll"


async def test_dispatch_sync_webhook_type():
    """dispatch_sync with type='webhook' encodes the type correctly."""
    mock_conn = AsyncMock()
    pool = _make_pool()

    with _patch_get_conn(mock_conn):
        await dispatch_sync(
            pool, "int-1", "cal-1",
            provider="google_calendar",
            notify_type="webhook",
            channel_id="ch-1",
            resource_id="res-1",
            resource_state="exists",
        )

    _, raw_payload = mock_conn.execute.call_args.args
    data = json.loads(raw_payload)
    assert data["type"] == "webhook"
    assert data["channel_id"] == "ch-1"
