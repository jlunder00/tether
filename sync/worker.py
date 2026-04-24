"""Tether sync worker.

Owns:
  - PG LISTEN on the `integration_sync` channel
  - APScheduler cron for watch channel renewal (daily, <24h to expiry)
  - APScheduler cron for proactive token refresh (hourly, <1h to expiry)

The worker is intentionally provider-agnostic: it dispatches to the
correct SyncProvider via the integrations registry and lets the provider
own the business logic. Swapping the dispatch layer (today: PG NOTIFY,
future: arq/Redis) only requires changing sync/dispatch.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db.postgres as pg
import integrations.registry as registry
from integrations.models import WebhookPayload

logger = logging.getLogger(__name__)

_LISTEN_CHANNEL = "integration_sync"


class SyncWorker:
    """Manages the LISTEN loop and scheduled maintenance jobs.

    Lifecycle:
        worker = SyncWorker(pool)
        await worker.start()     # starts scheduler and listener
        await worker.wait()      # blocks until stop() is called
        await worker.stop()      # shuts down gracefully
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._scheduler = AsyncIOScheduler()
        self._listen_conn: asyncpg.Connection | None = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open the dedicated LISTEN connection and start cron jobs."""
        dsn = os.environ.get("DATABASE_URL")
        self._listen_conn = await asyncpg.connect(dsn)
        await self._listen_conn.add_listener(_LISTEN_CHANNEL, self._on_notify)
        logger.info("Listening on PG channel '%s'", _LISTEN_CHANNEL)

        self._scheduler.add_job(
            self._renew_expiring_watches,
            "cron",
            hour=3,          # daily at 03:00 UTC
            minute=0,
            id="renew_watches",
        )
        self._scheduler.add_job(
            self._refresh_expiring_tokens,
            "cron",
            minute=0,        # top of every hour
            id="refresh_tokens",
        )
        self._scheduler.start()
        logger.info("Scheduler started")

    async def wait(self) -> None:
        """Block until stop() signals the stop event."""
        await self._stop_event.wait()

    async def stop(self) -> None:
        """Graceful shutdown: stop scheduler and close LISTEN connection."""
        logger.info("Stopping sync worker")
        self._scheduler.shutdown(wait=False)
        if self._listen_conn and not self._listen_conn.is_closed():
            await self._listen_conn.remove_listener(_LISTEN_CHANNEL, self._on_notify)
            await self._listen_conn.close()
        self._stop_event.set()

    # ------------------------------------------------------------------
    # LISTEN callback
    # ------------------------------------------------------------------

    async def _on_notify(
        self,
        conn: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Callback fired by asyncpg on each NOTIFY to `integration_sync`.

        Parses the JSON payload, looks up the provider, and dispatches
        to handle_webhook() or poll() depending on the notify type.

        All exceptions are caught here: asyncpg silently swallows
        exceptions raised in listener callbacks, so we must log them
        explicitly.
        """
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.exception("Malformed NOTIFY payload (not JSON): %r", payload)
            return

        provider_name = data.get("provider", "")
        integration_id = data.get("integration_id", "")
        calendar_id = data.get("calendar_id", "")
        notify_type = data.get("type", "poll")

        try:
            sync_cls = registry.get_sync(provider_name)
        except KeyError:
            logger.error("Unknown provider '%s' in NOTIFY payload", provider_name)
            return

        provider = sync_cls(self._pool)

        try:
            if notify_type == "webhook":
                webhook_payload = WebhookPayload(
                    channel_id=data.get("channel_id", ""),
                    resource_id=data.get("resource_id", ""),
                    resource_state=data.get("resource_state", ""),
                    raw_headers=data,
                )
                await provider.handle_webhook(integration_id, webhook_payload)
            else:
                await provider.poll(integration_id, calendar_id, since_cursor=None)
        except Exception:
            logger.exception(
                "Error processing %s sync for integration=%s calendar=%s",
                notify_type,
                integration_id,
                calendar_id,
            )

    # ------------------------------------------------------------------
    # Scheduled maintenance jobs
    # ------------------------------------------------------------------

    async def _renew_expiring_watches(self) -> None:
        """Renew watch channels expiring within the next 24 hours.

        Queries integration_sync_state joined to user_integrations to get
        the provider name, then calls provider.renew_webhook(sync_state_id).
        """
        async with pg.get_conn(self._pool) as conn:
            rows = await conn.fetch(
                """
                SELECT s.id, s.integration_id, i.provider
                FROM integration_sync_state s
                JOIN user_integrations i ON i.id = s.integration_id
                WHERE s.watch_expiry < now() + interval '1 day'
                  AND i.enabled = true
                """,
            )

        for row in rows:
            provider_name = row["provider"]
            sync_state_id = str(row["id"])
            try:
                sync_cls = registry.get_sync(provider_name)
                provider = sync_cls(self._pool)
                await provider.renew_webhook(sync_state_id)
                logger.info("Renewed watch channel for sync_state %s", sync_state_id)
            except Exception:
                logger.exception(
                    "Failed to renew watch channel for sync_state %s", sync_state_id
                )

    async def _refresh_expiring_tokens(self) -> None:
        """Pre-refresh access tokens expiring within the next hour.

        Proactive refresh ensures sync operations never block waiting
        on a token refresh mid-operation.
        """
        async with pg.get_conn(self._pool) as conn:
            rows = await conn.fetch(
                """
                SELECT id, provider
                FROM user_integrations
                WHERE token_expiry < now() + interval '1 hour'
                  AND enabled = true
                  AND refresh_token IS NOT NULL
                """,
            )

        for row in rows:
            provider_name = row["provider"]
            integration_id = str(row["id"])
            try:
                oauth_cls = registry.get_oauth(provider_name)
                provider = oauth_cls(self._pool)
                await provider.refresh_token(integration_id)
                logger.info("Refreshed token for integration %s", integration_id)
            except Exception:
                logger.exception(
                    "Failed to refresh token for integration %s", integration_id
                )
