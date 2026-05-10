"""Unit tests for bot/webhook_setup.py — mocks httpx, no network calls."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_register_webhook_calls_telegram_api():
    """register_webhook POSTs to Telegram setWebhook with correct params."""
    from bot.webhook_setup import register_webhook

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"ok": True, "result": True}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await register_webhook(
            bot_token="12345:ABC",
            webhook_url="https://example.com/api/bot/telegram-webhook",
            secret="my-secret",
        )

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    url = call_args[0][0]
    posted_json = call_args[1].get("json", {})
    # URL must target the correct Telegram endpoint
    assert "12345:ABC" in url
    assert "setWebhook" in url
    # Payload must include the webhook URL and secret
    assert posted_json.get("url") == "https://example.com/api/bot/telegram-webhook"
    assert posted_json.get("secret_token") == "my-secret"


@pytest.mark.asyncio
async def test_deregister_webhook_calls_telegram_api():
    """deregister_webhook POSTs to Telegram deleteWebhook."""
    from bot.webhook_setup import deregister_webhook

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"ok": True, "result": True}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await deregister_webhook(bot_token="12345:ABC")

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert "12345:ABC" in url
    assert "deleteWebhook" in url


@pytest.mark.asyncio
async def test_register_webhook_idempotent_on_ok_true():
    """register_webhook does not raise when Telegram returns ok=True."""
    from bot.webhook_setup import register_webhook

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"ok": True, "result": True}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        # Should not raise
        await register_webhook("tok", "https://example.com/webhook", "secret")


@pytest.mark.asyncio
async def test_register_webhook_logs_warning_on_ok_false(caplog):
    """register_webhook logs a warning when Telegram returns ok=False."""
    import logging
    from bot.webhook_setup import register_webhook

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"ok": False, "description": "Bad request"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="bot.webhook_setup"):
            await register_webhook("tok", "https://example.com/webhook", "secret")

    assert any("ok=False" in r.message or "Bad request" in r.message for r in caplog.records)
