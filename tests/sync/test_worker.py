"""Tests for the tether-sync worker.

Most tests mock the asyncpg pool and provider so they run without a live DB.
The watch-renewal and token-refresh tests patch pg.get_conn directly to avoid
having to replicate asyncpg's transaction() context-manager internals.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from integrations.models import WebhookPayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pool():
    """Return a minimal mock pool (only used to construct SyncWorker)."""
    return MagicMock()


def _patch_get_conn(mock_conn):
    """Patch pg.get_conn to yield *mock_conn* as an async context manager."""
    @asynccontextmanager
    async def _fake_get_conn(pool, user_id=None):
        yield mock_conn

    return patch("db.postgres.get_conn", side_effect=_fake_get_conn)


def _webhook_notify_payload(
    provider: str = "google_calendar",
    integration_id: str = "int-1",
    calendar_id: str = "cal-1",
    channel_id: str = "ch-1",
    resource_id: str = "res-1",
    resource_state: str = "exists",
) -> str:
    return json.dumps({
        "type": "webhook",
        "provider": provider,
        "integration_id": integration_id,
        "calendar_id": calendar_id,
        "channel_id": channel_id,
        "resource_id": resource_id,
        "resource_state": resource_state,
    })


def _poll_notify_payload(
    provider: str = "google_calendar",
    integration_id: str = "int-1",
    calendar_id: str = "cal-1",
) -> str:
    return json.dumps({
        "type": "poll",
        "provider": provider,
        "integration_id": integration_id,
        "calendar_id": calendar_id,
    })


# ---------------------------------------------------------------------------
# _on_notify: webhook type calls provider.handle_webhook
# ---------------------------------------------------------------------------

async def test_on_notify_webhook_calls_handle_webhook():
    """NOTIFY with type=webhook calls the provider's handle_webhook."""
    from sync.worker import SyncWorker

    pool = _make_pool()
    worker = SyncWorker(pool)

    mock_provider = AsyncMock()
    mock_sync_cls = MagicMock(return_value=mock_provider)

    payload = _webhook_notify_payload()

    with patch("sync.worker.registry.get_sync", return_value=mock_sync_cls):
        await worker._on_notify(None, None, "integration_sync", payload)

    mock_provider.handle_webhook.assert_awaited_once()
    args = mock_provider.handle_webhook.call_args
    assert args.args[0] == "int-1"
    assert isinstance(args.args[1], WebhookPayload)
    assert args.args[1].resource_state == "exists"


# ---------------------------------------------------------------------------
# _on_notify: poll type calls provider.poll
# ---------------------------------------------------------------------------

async def test_on_notify_poll_calls_poll():
    """NOTIFY with type=poll calls the provider's poll method."""
    from sync.worker import SyncWorker

    pool = _make_pool()
    worker = SyncWorker(pool)

    mock_provider = AsyncMock()
    mock_provider.poll.return_value = "new-sync-token"
    mock_sync_cls = MagicMock(return_value=mock_provider)

    payload = _poll_notify_payload()

    with patch("sync.worker.registry.get_sync", return_value=mock_sync_cls):
        await worker._on_notify(None, None, "integration_sync", payload)

    mock_provider.poll.assert_awaited_once_with("int-1", "cal-1", since_cursor=None)


# ---------------------------------------------------------------------------
# _on_notify: unknown provider logs error, does not crash
# ---------------------------------------------------------------------------

async def test_on_notify_unknown_provider_does_not_crash():
    """NOTIFY for an unregistered provider logs an error and does not raise."""
    from sync.worker import SyncWorker

    pool = _make_pool()
    worker = SyncWorker(pool)

    payload = json.dumps({
        "type": "poll",
        "provider": "no_such_provider",
        "integration_id": "x",
        "calendar_id": "y",
    })

    # Should not raise — just log
    await worker._on_notify(None, None, "integration_sync", payload)


# ---------------------------------------------------------------------------
# _on_notify: malformed payload logs error, does not crash
# ---------------------------------------------------------------------------

async def test_on_notify_malformed_payload_does_not_crash():
    """NOTIFY with non-JSON payload logs an error and does not raise."""
    from sync.worker import SyncWorker

    pool = _make_pool()
    worker = SyncWorker(pool)

    await worker._on_notify(None, None, "integration_sync", "not-json")


# ---------------------------------------------------------------------------
# _renew_expiring_watches: calls renew_webhook for each expiring state
# ---------------------------------------------------------------------------

async def test_renew_expiring_watches_calls_renew_webhook():
    """Renewal cron calls renew_webhook for each sync_state with expiry within 24h."""
    from sync.worker import SyncWorker

    pool = _make_pool()
    expiring_rows = [
        {"id": "state-1", "integration_id": "int-1", "provider": "google_calendar"},
        {"id": "state-2", "integration_id": "int-2", "provider": "google_calendar"},
    ]

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=expiring_rows)

    mock_provider = AsyncMock()
    mock_sync_cls = MagicMock(return_value=mock_provider)

    worker = SyncWorker(pool)

    with _patch_get_conn(mock_conn), \
         patch("sync.worker.registry.get_sync", return_value=mock_sync_cls):
        await worker._renew_expiring_watches()

    assert mock_provider.renew_webhook.await_count == 2
    calls_args = [c.args[0] for c in mock_provider.renew_webhook.await_args_list]
    assert "state-1" in calls_args
    assert "state-2" in calls_args


# ---------------------------------------------------------------------------
# _refresh_expiring_tokens: calls refresh_token for each expiring integration
# ---------------------------------------------------------------------------

async def test_refresh_expiring_tokens_calls_refresh_token():
    """Token-refresh cron calls refresh_token for each integration expiring within 1h."""
    from sync.worker import SyncWorker

    pool = _make_pool()
    expiring_rows = [
        {"id": "int-1", "provider": "google_calendar"},
        {"id": "int-2", "provider": "google_calendar"},
    ]

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=expiring_rows)

    mock_oauth_cls = MagicMock()
    mock_oauth = AsyncMock()
    mock_oauth_cls.return_value = mock_oauth

    worker = SyncWorker(pool)

    with _patch_get_conn(mock_conn), \
         patch("sync.worker.registry.get_oauth", return_value=mock_oauth_cls):
        await worker._refresh_expiring_tokens()

    assert mock_oauth.refresh_token.await_count == 2
    refreshed_ids = [c.args[0] for c in mock_oauth.refresh_token.await_args_list]
    assert "int-1" in refreshed_ids
    assert "int-2" in refreshed_ids


# ---------------------------------------------------------------------------
# dispatch_sync: issues PG NOTIFY with correct JSON payload
# ---------------------------------------------------------------------------

async def test_dispatch_sync_issues_pg_notify():
    """dispatch_sync calls pg_notify with properly encoded JSON."""
    from sync.dispatch import dispatch_sync

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
    from sync.dispatch import dispatch_sync

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
