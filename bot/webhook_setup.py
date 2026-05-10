"""Telegram webhook registration helpers.

Call register_webhook() on startup when TELEGRAM_WEBHOOK_URL is set.
Call deregister_webhook() when switching back to polling mode.

Both functions are idempotent — safe to call on every startup.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


async def register_webhook(bot_token: str, webhook_url: str, secret: str) -> None:
    """Call Telegram setWebhook. Idempotent — safe to call on every startup.

    Args:
        bot_token:   Telegram bot token (e.g. "12345:ABC...").
        webhook_url: Public HTTPS URL Telegram will POST updates to.
        secret:      Value sent in X-Telegram-Bot-Api-Secret-Token header.
                     Must match TELEGRAM_WEBHOOK_SECRET env var on the receiving end.
    """
    url = _TELEGRAM_API.format(token=bot_token, method="setWebhook")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json={"url": webhook_url, "secret_token": secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("ok"):
        logger.info("register_webhook: Telegram webhook registered → %s", webhook_url)
    else:
        logger.warning(
            "register_webhook: Telegram returned ok=False — %s",
            data.get("description", "no description"),
        )


async def deregister_webhook(bot_token: str) -> None:
    """Call Telegram deleteWebhook. Used when switching back to polling."""
    url = _TELEGRAM_API.format(token=bot_token, method="deleteWebhook")
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

    if data.get("ok"):
        logger.info("deregister_webhook: Telegram webhook removed")
    else:
        logger.warning(
            "deregister_webhook: Telegram returned ok=False — %s",
            data.get("description", "no description"),
        )
