"""Dispatch layer — triggers a sync by issuing PG NOTIFY.

API routes call dispatch_sync() on webhook receipt or manual sync.
Today this issues a PG NOTIFY on the `integration_sync` channel.
Future upgrade path: swap this module for an arq/Redis enqueue
without changing any SyncProvider code.
"""
from __future__ import annotations

import json

import asyncpg

import db.postgres as pg


async def dispatch_sync(
    pool: asyncpg.Pool,
    integration_id: str,
    calendar_id: str,
    *,
    provider: str,
    notify_type: str = "poll",
    **extra: object,
) -> None:
    """Issue a PG NOTIFY to the integration_sync channel.

    Args:
        pool: asyncpg connection pool.
        integration_id: ID of the user_integrations row.
        calendar_id: Which calendar to sync.
        provider: Provider name (e.g. "google_calendar") used by the worker
                  to look up the correct SyncProvider class.
        notify_type: "poll" for incremental/manual sync, "webhook" for
                     push-notification triggered sync.
        **extra: Additional fields forwarded verbatim in the payload
                 (e.g. channel_id, resource_id, resource_state for webhooks).
    """
    payload = json.dumps({
        "type": notify_type,
        "integration_id": integration_id,
        "calendar_id": calendar_id,
        "provider": provider,
        **extra,
    })
    async with pg.get_conn(pool) as conn:
        await conn.execute("SELECT pg_notify('integration_sync', $1)", payload)
