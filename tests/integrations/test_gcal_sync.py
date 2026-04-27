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
# poll — singleEvents=false (recurring events as series masters)
# ---------------------------------------------------------------------------

async def test_poll_does_not_send_single_events_true():
    """poll() must NOT send singleEvents=true — recurring events need series masters."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)

    mock_conn = AsyncMock()
    resp = _make_response([])

    captured_params: list[dict] = []

    async def fake_get(url, headers, params):
        captured_params.append(dict(params))
        return resp

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get

            with _patch_get_conn(mock_conn):
                with patch("integrations.google_calendar.sync.upsert_sync_state", new=AsyncMock(return_value={})):
                    await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)

    assert captured_params, "No HTTP GET captured"
    first_params = captured_params[0]
    assert first_params.get("singleEvents") != "true", \
        "singleEvents=true must not be sent (would expand recurring events)"


# ---------------------------------------------------------------------------
# poll — pagination: walks all pages, persists final syncToken
# ---------------------------------------------------------------------------

async def _run_paginated_poll(sync, page_responses: list[MagicMock], mock_conn: AsyncMock) -> str:
    """Helper: run poll() with a sequence of paginated responses."""
    call_count = 0

    async def fake_get(url, headers, params):
        nonlocal call_count
        resp = page_responses[call_count]
        call_count += 1
        return resp

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get

            with _patch_get_conn(mock_conn):
                with patch(
                    "integrations.google_calendar.sync.soft_delete_task_by_external_id",
                    new=AsyncMock(),
                ):
                    with patch(
                        "integrations.google_calendar.sync.upsert_task_from_draft",
                        new=AsyncMock(return_value={}),
                    ):
                        with patch(
                            "integrations.google_calendar.sync.upsert_sync_state",
                            new=AsyncMock(return_value={}),
                        ):
                            return await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)


def _page_response(items: list[dict], *, next_page_token: str | None = None, next_sync_token: str | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    data: dict = {"items": items}
    if next_page_token:
        data["nextPageToken"] = next_page_token
    if next_sync_token:
        data["nextSyncToken"] = next_sync_token
    resp.json.return_value = data
    return resp


async def test_poll_pagination_walks_all_pages():
    """poll() follows nextPageToken across all pages before returning."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)
    mock_conn = AsyncMock()

    page1 = _page_response([_active_event("evt-1")], next_page_token="page2-tok")
    page2 = _page_response([_active_event("evt-2")], next_page_token="page3-tok")
    page3 = _page_response([_active_event("evt-3")], next_sync_token=_NEW_SYNC_TOKEN)

    with patch(
        "integrations.google_calendar.sync.upsert_task_from_draft",
        new=AsyncMock(return_value={}),
    ) as mock_upsert:
        with patch.object(sync, "_get_integration_row", new=AsyncMock(
            return_value={"user_id": _USER_ID, "access_token": "tok"}
        )):
            call_count = 0
            responses = [page1, page2, page3]

            async def fake_get(url, headers, params):
                nonlocal call_count
                r = responses[call_count]
                call_count += 1
                return r

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = fake_get

                with _patch_get_conn(mock_conn):
                    with patch("integrations.google_calendar.sync.soft_delete_task_by_external_id", new=AsyncMock()):
                        with patch("integrations.google_calendar.sync.upsert_sync_state", new=AsyncMock(return_value={})):
                            result = await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)

    assert call_count == 3, f"Expected 3 HTTP requests (one per page), got {call_count}"
    assert result == _NEW_SYNC_TOKEN
    assert mock_upsert.await_count == 3


async def test_poll_pagination_uses_page_token_not_sync_token():
    """Subsequent page requests must use pageToken, not syncToken."""
    pool = _make_pool()
    sync = GoogleCalendarSync(pool)
    mock_conn = AsyncMock()

    captured_params: list[dict] = []
    page1 = _page_response([_active_event("e1")], next_page_token="page2-tok")
    page2 = _page_response([_active_event("e2")], next_sync_token=_NEW_SYNC_TOKEN)

    async def fake_get(url, headers, params):
        captured_params.append(dict(params))
        return [page1, page2][len(captured_params) - 1]

    with patch.object(sync, "_get_integration_row", new=AsyncMock(
        return_value={"user_id": _USER_ID, "access_token": "tok"}
    )):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get

            with _patch_get_conn(mock_conn):
                with patch("integrations.google_calendar.sync.soft_delete_task_by_external_id", new=AsyncMock()):
                    with patch("integrations.google_calendar.sync.upsert_task_from_draft", new=AsyncMock(return_value={})):
                        with patch("integrations.google_calendar.sync.upsert_sync_state", new=AsyncMock(return_value={})):
                            await sync.poll(_INTEGRATION_ID, _CALENDAR_ID, _SYNC_TOKEN)

    assert len(captured_params) == 2
    # First request uses syncToken
    assert "syncToken" in captured_params[0]
    # Second request uses pageToken, NOT syncToken
    assert "pageToken" in captured_params[1]
    assert "syncToken" not in captured_params[1]


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


# ---------------------------------------------------------------------------
# upsert_sync_state — COALESCE preserves watch fields when syncing cursor only
# ---------------------------------------------------------------------------

async def test_upsert_sync_state_preserves_watch_fields_on_cursor_update():
    """Updating only sync_cursor must not overwrite existing watch channel fields with NULL.

    poll() calls upsert_sync_state with only sync_cursor set. On conflict, the SQL
    must COALESCE incoming NULLs against the existing watch_channel_id / watch_expiry /
    watch_resource_id values — not blindly replace them.

    This test verifies the SQL sent to the DB contains COALESCE for watch fields.
    """
    from db.pg_queries.integrations import upsert_sync_state

    captured_sql: list[str] = []
    captured_args: list[tuple] = []

    mock_conn = AsyncMock()

    async def fake_fetchrow(sql, *args):
        captured_sql.append(sql)
        captured_args.append(args)
        # Return a minimal row so _row() doesn't blow up
        return {
            "integration_id": uuid.UUID(_INTEGRATION_ID),
            "calendar_id": _CALENDAR_ID,
            "sync_cursor": _NEW_SYNC_TOKEN,
            "watch_channel_id": "existing-ch",
            "watch_expiry": None,
            "watch_resource_id": "existing-res",
            "updated_at": None,
        }

    mock_conn.fetchrow = fake_fetchrow

    await upsert_sync_state(mock_conn, _INTEGRATION_ID, _CALENDAR_ID, sync_cursor=_NEW_SYNC_TOKEN)

    assert len(captured_sql) == 1, "upsert_sync_state should execute exactly one query"
    sql = captured_sql[0].upper()

    # The ON CONFLICT clause must use COALESCE for the three watch fields
    assert "COALESCE" in sql, (
        "upsert_sync_state ON CONFLICT must use COALESCE to preserve existing "
        "watch_channel_id / watch_expiry / watch_resource_id when called with only sync_cursor"
    )
