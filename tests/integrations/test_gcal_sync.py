"""Tests for GoogleCalendarSync.poll() and GoogleCalendarSync.handle_webhook().

All DB and HTTP calls are mocked — no live DB or network required.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
import pytest

from integrations.google_calendar.sync import GoogleCalendarSync
from integrations.models import TaskDraft, WebhookPayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INTEGRATION_ID = str(uuid.uuid4())
_CALENDAR_ID = "primary"
_USER_ID = str(uuid.uuid4())
_SYNC_TOKEN = "tok_abc123"
_NEW_SYNC_TOKEN = "tok_xyz456"


def _make_pool() -> MagicMock:
    return MagicMock()


def _patch_get_conn(mock_conn):
    """Patch pg.get_conn to yield *mock_conn* as an async context manager."""
    @asynccontextmanager
    async def _fake(pool, user_id=None):
        yield mock_conn

    return patch("db.postgres.get_conn", side_effect=_fake)


def _make_response(items: list[dict], next_sync_token: str = _NEW_SYNC_TOKEN, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"items": items, "nextSyncToken": next_sync_token}
    resp.raise_for_status = MagicMock()
    return resp


def _active_event(event_id: str = "evt-1") -> dict:
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": "Team sync",
        "start": {"dateTime": "2026-04-26T10:00:00+00:00"},
        "end": {"dateTime": "2026-04-26T11:00:00+00:00"},
    }


def _cancelled_event(event_id: str = "evt-del") -> dict:
    return {"id": event_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# poll — 410 raises ValueError
# ---------------------------------------------------------------------------

async def test_poll_raises_on_410():
    """A 410 response from Google raises ValueError (invalidated token)."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    resp_410 = MagicMock()
    resp_410.status_code = 410

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=resp_410)

            with pytest.raises(ValueError, match="410"):
                await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)


# ---------------------------------------------------------------------------
# poll — cancelled items → soft_delete_task_by_external_id
# ---------------------------------------------------------------------------

async def test_poll_cancelled_item_calls_soft_delete():
    """Cancelled items trigger soft_delete_task_by_external_id."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    mock_conn = AsyncMock()
    resp = _make_response([_cancelled_event("evt-del")])

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=resp)

            with _patch_get_conn(mock_conn):
                with patch(
                    "integrations.google_calendar.sync.soft_delete_task_by_external_id",
                    new=AsyncMock(return_value=True),
                ) as mock_delete:
                    with patch(
                        "integrations.google_calendar.sync.upsert_task_from_draft",
                        new=AsyncMock(),
                    ):
                        with patch(
                            "integrations.google_calendar.sync.upsert_sync_state",
                            new=AsyncMock(return_value={}),
                        ):
                            await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)

    mock_delete.assert_awaited_once_with(mock_conn, _USER_ID, "google_calendar", "evt-del")


# ---------------------------------------------------------------------------
# poll — active items → normalize + upsert
# ---------------------------------------------------------------------------

async def test_poll_active_item_calls_upsert():
    """Active items are normalized and passed to upsert_task_from_draft."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    mock_conn = AsyncMock()
    resp = _make_response([_active_event("evt-1")])

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=resp)

            with _patch_get_conn(mock_conn):
                with patch(
                    "integrations.google_calendar.sync.soft_delete_task_by_external_id",
                    new=AsyncMock(),
                ):
                    with patch(
                        "integrations.google_calendar.sync.upsert_task_from_draft",
                        new=AsyncMock(return_value={"id": "uuid-1"}),
                    ) as mock_upsert:
                        with patch(
                            "integrations.google_calendar.sync.upsert_sync_state",
                            new=AsyncMock(return_value={}),
                        ):
                            await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)

    mock_upsert.assert_awaited_once()
    call_args = mock_upsert.call_args
    assert call_args.args[0] is mock_conn
    assert call_args.args[1] == _USER_ID
    draft: TaskDraft = call_args.args[2]
    assert draft.external_id == "evt-1"
    assert draft.source == "google_calendar"


# ---------------------------------------------------------------------------
# poll — sync token persisted
# ---------------------------------------------------------------------------

async def test_poll_persists_sync_token():
    """New syncToken is persisted via upsert_sync_state."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    mock_conn = AsyncMock()
    resp = _make_response([], next_sync_token=_NEW_SYNC_TOKEN)

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=resp)

            with _patch_get_conn(mock_conn):
                with patch(
                    "integrations.google_calendar.sync.soft_delete_task_by_external_id",
                    new=AsyncMock(),
                ):
                    with patch(
                        "integrations.google_calendar.sync.upsert_task_from_draft",
                        new=AsyncMock(),
                    ):
                        with patch(
                            "integrations.google_calendar.sync.upsert_sync_state",
                            new=AsyncMock(return_value={}),
                        ) as mock_upsert_state:
                            await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)

    mock_upsert_state.assert_awaited_once_with(
        mock_conn, _INTEGRATION_ID, _CALENDAR_ID, sync_cursor=_NEW_SYNC_TOKEN
    )


# ---------------------------------------------------------------------------
# poll — returns new sync token
# ---------------------------------------------------------------------------

async def test_poll_returns_new_sync_token():
    """poll() returns the new syncToken from the Google response."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    mock_conn = AsyncMock()
    resp = _make_response([], next_sync_token=_NEW_SYNC_TOKEN)

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=resp)

            with _patch_get_conn(mock_conn):
                with patch("integrations.google_calendar.sync.soft_delete_task_by_external_id", new=AsyncMock()):
                    with patch("integrations.google_calendar.sync.upsert_task_from_draft", new=AsyncMock()):
                        with patch("integrations.google_calendar.sync.upsert_sync_state", new=AsyncMock(return_value={})):
                            result = await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)

    assert result == _NEW_SYNC_TOKEN


# ---------------------------------------------------------------------------
# poll — mixed items processed correctly
# ---------------------------------------------------------------------------

async def test_poll_mixed_items_routes_correctly():
    """Cancelled items go to soft_delete, active items go to upsert."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    mock_conn = AsyncMock()
    items = [_active_event("evt-1"), _cancelled_event("evt-del"), _active_event("evt-2")]
    resp = _make_response(items)

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=resp)

            with _patch_get_conn(mock_conn):
                with patch(
                    "integrations.google_calendar.sync.soft_delete_task_by_external_id",
                    new=AsyncMock(return_value=True),
                ) as mock_delete:
                    with patch(
                        "integrations.google_calendar.sync.upsert_task_from_draft",
                        new=AsyncMock(return_value={}),
                    ) as mock_upsert:
                        with patch("integrations.google_calendar.sync.upsert_sync_state", new=AsyncMock(return_value={})):
                            await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)

    assert mock_delete.await_count == 1
    assert mock_upsert.await_count == 2


# ---------------------------------------------------------------------------
# poll — warns when nextPageToken present
# ---------------------------------------------------------------------------

async def test_poll_warns_on_next_page_token(caplog):
    """poll() logs a warning when nextPageToken is present (pagination not implemented)."""
    import logging
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    mock_conn = AsyncMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "items": [],
        "nextPageToken": "page-tok",
        "nextSyncToken": _NEW_SYNC_TOKEN,
    }

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=resp)

            with _patch_get_conn(mock_conn):
                with patch("integrations.google_calendar.sync.upsert_sync_state", new=AsyncMock(return_value={})):
                    with caplog.at_level(logging.WARNING, logger="integrations.google_calendar.sync"):
                        await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)

    assert any("nextPageToken" in r.message or "pagination" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# handle_webhook — looks up sync state by channel_id and calls poll
# ---------------------------------------------------------------------------

async def test_handle_webhook_calls_poll():
    """handle_webhook fetches sync state by channel_id and calls self.poll()."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={
        "calendar_id": _CALENDAR_ID,
        "sync_cursor": _SYNC_TOKEN,
    })

    payload = WebhookPayload(
        channel_id="ch-1",
        resource_id="res-1",
        resource_state="exists",
    )

    with _patch_get_conn(mock_conn):
        with patch.object(sync, "poll", new=AsyncMock(return_value=_NEW_SYNC_TOKEN)) as mock_poll:
            await sync.handle_webhook(_INTEGRATION_ID, payload)

    mock_poll.assert_awaited_once_with(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)


# ---------------------------------------------------------------------------
# handle_webhook — unknown channel logs and skips (no crash)
# ---------------------------------------------------------------------------

async def test_handle_webhook_unknown_channel_skips():
    """handle_webhook with no matching sync state logs a warning and returns."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)

    payload = WebhookPayload(
        channel_id="ch-unknown",
        resource_id="res-x",
        resource_state="exists",
    )

    with _patch_get_conn(mock_conn):
        with patch.object(sync, "poll", new=AsyncMock()) as mock_poll:
            # Must not raise
            await sync.handle_webhook(_INTEGRATION_ID, payload)

    mock_poll.assert_not_awaited()
