"""Integration tests for POST /api/bot/telegram-webhook endpoint."""
from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, patch

# Valid Telegram Update payload (minimal message update)
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

VALID_SECRET = "test-webhook-secret"
WRONG_SECRET = "wrong-secret"


@pytest.fixture
def webhook_app_no_db():
    """App with TELEGRAM_WEBHOOK_SECRET set but no real DB pool (for auth rejection tests)."""
    os.environ["TELEGRAM_WEBHOOK_SECRET"] = VALID_SECRET
    from api.main import create_app

    app = create_app()
    # Minimal state — no pool needed for 403 rejection (happens before DB access)
    app.state.pool = None
    app.state.vault = None
    yield app
    os.environ.pop("TELEGRAM_WEBHOOK_SECRET", None)


@pytest.fixture
def webhook_app(pool):
    """App with TELEGRAM_WEBHOOK_SECRET set and real pool for processing tests."""
    os.environ["TELEGRAM_WEBHOOK_SECRET"] = VALID_SECRET
    from api.main import create_app

    app = create_app()
    app.state.pool = pool
    app.state.vault = None
    yield app
    os.environ.pop("TELEGRAM_WEBHOOK_SECRET", None)


@pytest.mark.asyncio
async def test_webhook_invalid_secret_returns_403(webhook_app_no_db):
    """Wrong secret header → 403 immediately, no processing."""
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=webhook_app_no_db),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/bot/telegram-webhook",
            json=SAMPLE_UPDATE,
            headers={"X-Telegram-Bot-Api-Secret-Token": WRONG_SECRET},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_webhook_missing_secret_returns_403(webhook_app_no_db):
    """Missing secret header → 403."""
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=webhook_app_no_db),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/bot/telegram-webhook",
            json=SAMPLE_UPDATE,
            # No header
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_webhook_valid_secret_returns_200(webhook_app):
    """Valid secret header → 200, message queued for background processing."""
    from httpx import AsyncClient, ASGITransport

    with patch("api.routes.bot._process_telegram_update", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=webhook_app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/bot/telegram-webhook",
                json=SAMPLE_UPDATE,
                headers={"X-Telegram-Bot-Api-Secret-Token": VALID_SECRET},
            )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_non_message_update_returns_200(webhook_app):
    """Non-message updates (e.g. edited_message) are accepted silently."""
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
            transport=ASGITransport(app=webhook_app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/bot/telegram-webhook",
                json=edited_update,
                headers={"X-Telegram-Bot-Api-Secret-Token": VALID_SECRET},
            )
    assert resp.status_code == 200
