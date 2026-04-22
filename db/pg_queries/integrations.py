"""Integration query stubs — user_integrations + integration_sync_state.

These will be filled in by the Google Calendar adapter implementation.
All functions take conn: asyncpg.Connection as first argument.
"""
from __future__ import annotations

import asyncpg


async def get_integration(
    conn: asyncpg.Connection,
    user_id: str,
    provider: str,
) -> dict | None:
    """Return the user_integrations row for (user_id, provider), or None."""
    raise NotImplementedError


async def upsert_integration(
    conn: asyncpg.Connection,
    user_id: str,
    provider: str,
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    token_expiry=None,
    scopes: list[str] | None = None,
    metadata: dict | None = None,
    enabled: bool = True,
) -> dict:
    """Insert or update a user_integrations row. Returns the resulting row."""
    raise NotImplementedError


async def delete_integration(
    conn: asyncpg.Connection,
    user_id: str,
    provider: str,
) -> bool:
    """Delete the integration for (user_id, provider). Returns True if a row was deleted."""
    raise NotImplementedError


async def get_sync_state(
    conn: asyncpg.Connection,
    integration_id: str,
    calendar_id: str,
) -> dict | None:
    """Return the integration_sync_state row for (integration_id, calendar_id), or None."""
    raise NotImplementedError


async def upsert_sync_state(
    conn: asyncpg.Connection,
    integration_id: str,
    calendar_id: str,
    *,
    sync_cursor: str | None = None,
    watch_channel_id: str | None = None,
    watch_expiry=None,
    watch_resource_id: str | None = None,
) -> dict:
    """Insert or update an integration_sync_state row. Returns the resulting row."""
    raise NotImplementedError
