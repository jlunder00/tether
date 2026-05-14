"""Integration tests for POST /api/bot/telegram-webhook endpoint.

Phase E: header-based per-user routing.
- Endpoint ALWAYS returns 200 (Telegram retries on non-200).
- Unknown or missing X-Telegram-Bot-Api-Secret-Token → 200, no dispatch.
- Valid secret resolves via DB lookup → BackgroundTask dispatched.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

import pytest

SAMPLE_UPDATE = {
    "update_id": 123456789,
    "message": {
        "message_id": 1,
        "from": {"id": 111, "is_bot": False, "first_name": "Test"},
        "chat": {"id": 111, "type": "private"},
        "date": 1700000000,
        "text": "Hello bot",
    },
}

VALID_SECRET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


def _make_db_fixtures(user_id: str | None):
    """Build mock pool + get_conn context that returns user_id (or None)."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(
        return_value={"user_id": uuid.UUID(user_id)} if user_id else None
    )
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _fake_get_conn(p, uid=None):
        yield mock_conn

    return mock_pool, _fake_get_conn


@pytest.fixture
def webhook_app_valid_secret():
    """App whose DB lookup resolves VALID_SECRET to TEST_USER_ID."""
    mock_pool, fake_get_conn = _make_db_fixtures(TEST_USER_ID)
    from api.main import create_app
    app = create_app()
    app.state.pool = mock_pool
    app.state.vault = None
    with patch("db.postgres.get_conn", new=fake_get_conn):
        yield app


@pytest.fixture
def webhook_app_unknown_secret():
    """App whose DB lookup returns None for any secret."""
    mock_pool, fake_get_conn = _make_db_fixtures(None)
    from api.main import create_app
    app = create_app()
    app.state.pool = mock_pool
    app.state.vault = None
    with patch("db.postgres.get_conn", new=fake_get_conn):
        yield app


@pytest.mark.asyncio
async def test_webhook_always_returns_200_for_valid_secret(webhook_app_valid_secret):
    """Valid secret → 200."""
    from httpx import AsyncClient, ASGITransport

    with patch("api.routes.bot._process_telegram_update", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=webhook_app_valid_secret),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/bot/telegram-webhook",
                json=SAMPLE_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": VALID_SECRET},
            )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_returns_200_for_unknown_secret(webhook_app_unknown_secret):
    """Unknown secret → 200 (not 403), no BackgroundTask dispatched."""
    from httpx import AsyncClient, ASGITransport

    with patch(
        "api.routes.bot._process_telegram_update", new_callable=AsyncMock
    ) as mock_dispatch:
        async with AsyncClient(
            transport=ASGITransport(app=webhook_app_unknown_secret),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/bot/telegram-webhook",
                json=SAMPLE_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            )
    assert resp.status_code == 200
    mock_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_returns_200_for_missing_header(webhook_app_unknown_secret):
    """Missing header → 200, no dispatch."""
    from httpx import AsyncClient, ASGITransport

    with patch(
        "api.routes.bot._process_telegram_update", new_callable=AsyncMock
    ) as mock_dispatch:
        async with AsyncClient(
            transport=ASGITransport(app=webhook_app_unknown_secret),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/bot/telegram-webhook",
                json=SAMPLE_UPDATE,
            )
    assert resp.status_code == 200
    mock_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_non_message_update_returns_200(webhook_app_valid_secret):
    """Non-message updates are accepted and return 200."""
    from httpx import AsyncClient, ASGITransport

    edited_update = {
        "update_id": 999,
        "edited_message": {
            "message_id": 1,
            "chat": {"id": 111, "type": "private"},
            "date": 1700000000,
            "text": "edited",
        },
    }
    with patch("api.routes.bot._process_telegram_update", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=webhook_app_valid_secret),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/bot/telegram-webhook",
                json=edited_update,
                headers={"X-Telegram-Bot-Api-Secret-Token": VALID_SECRET},
            )
    assert resp.status_code == 200
