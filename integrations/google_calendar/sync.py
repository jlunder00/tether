"""Google Calendar SyncProvider implementation.

The actual sync execution (PG LISTEN, event import, anchor assignment)
lives in the tether-sync container — a separate workstream. This module
provides the interface that tether-sync will call.

register_webhook: registers a Google Calendar push channel.
renew_webhook: renews an expiring channel.
handle_webhook: stub — tether-sync calls this after receiving PG NOTIFY.
poll: fetches incremental changes via syncToken.
normalize_event: delegates to mapping.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncpg
import httpx

import api.config as cfg
from db.pg_queries.integrations import upsert_sync_state
from integrations.base import SyncProvider
from integrations.google_calendar.mapping import map_event
from integrations.models import TaskDraft, WebhookPayload

_CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
_CALENDAR_WATCH_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/watch"


class GoogleCalendarSync(SyncProvider):
    """SyncProvider for Google Calendar.

    Requires a pool for DB operations. HTTP calls use the access_token
    fetched from user_integrations.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _get_access_token(self, integration_id: str) -> str:
        """Fetch current access token for an integration."""
        import db.postgres as pg
        async with pg.get_conn(self._pool) as conn:
            row = await conn.fetchrow(
                "SELECT access_token FROM user_integrations WHERE id = $1",
                integration_id,
            )
        if not row:
            raise ValueError(f"Integration {integration_id} not found")
        return row["access_token"]

    async def register_webhook(
        self, integration_id: str, calendar_id: str
    ) -> None:
        """Register a Google Calendar push-notification channel.

        Stores the channel info in integration_sync_state so tether-sync
        knows how to handle incoming notifications.
        """
        import uuid
        access_token = await self._get_access_token(integration_id)
        channel_id = str(uuid.uuid4())
        # Watch channels expire after ~1 week (Google maximum)
        expiry = datetime.now(timezone.utc) + timedelta(days=7)
        expiry_ms = int(expiry.timestamp() * 1000)
        webhook_url = f"{cfg.GOOGLE_INTEGRATION_CALLBACK_URL.rsplit('/callback', 1)[0]}/webhook"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _CALENDAR_WATCH_URL.format(calendar_id=calendar_id),
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "id": channel_id,
                    "type": "web_hook",
                    "address": webhook_url,
                    "expiration": expiry_ms,
                },
            )
        data = resp.json()
        if resp.status_code not in (200, 201):
            raise ValueError(f"Google watch registration failed: {data}")

        import db.postgres as pg
        async with pg.get_conn(self._pool) as conn:
            await upsert_sync_state(
                conn,
                integration_id,
                calendar_id,
                watch_channel_id=data.get("id", channel_id),
                watch_expiry=datetime.fromtimestamp(
                    int(data.get("expiration", expiry_ms)) / 1000, tz=timezone.utc
                ),
                watch_resource_id=data.get("resourceId"),
            )

    async def renew_webhook(self, sync_state_id: str) -> None:
        """Renew an expiring watch channel. Called by tether-sync cron."""
        import db.postgres as pg
        async with pg.get_conn(self._pool) as conn:
            row = await conn.fetchrow(
                """
                SELECT s.*, i.id AS integration_id
                FROM integration_sync_state s
                JOIN user_integrations i ON i.id = s.integration_id
                WHERE s.id = $1
                """,
                sync_state_id,
            )
        if not row:
            return
        await self.register_webhook(str(row["integration_id"]), row["calendar_id"])

    async def handle_webhook(
        self, integration_id: str, payload: WebhookPayload
    ) -> None:
        """Process an inbound push notification. Called by tether-sync."""
        # Actual sync logic lives in tether-sync; this is the interface stub.
        pass

    async def poll(
        self,
        integration_id: str,
        calendar_id: str,
        since_cursor: str | None,
    ) -> str:
        """Fetch incremental changes via Google's syncToken mechanism.

        Returns the new syncToken to store as the next cursor.
        On 410 Gone (invalidated token), raises ValueError to trigger a full resync.
        """
        access_token = await self._get_access_token(integration_id)
        url = _CALENDAR_EVENTS_URL.format(calendar_id=calendar_id)
        params: dict = {"singleEvents": "true"}
        if since_cursor:
            params["syncToken"] = since_cursor
        else:
            # Initial import: 30 days back, no end limit
            from datetime import date
            thirty_days_ago = (
                datetime.now(timezone.utc) - timedelta(days=30)
            ).isoformat()
            params["timeMin"] = thirty_days_ago

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

        if resp.status_code == 410:
            raise ValueError("Sync token invalidated (410) — full resync needed")
        resp.raise_for_status()
        data = resp.json()
        return data.get("nextSyncToken", "")

    async def normalize_event(self, raw: dict) -> TaskDraft:
        return map_event(raw)
