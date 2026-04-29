"""Async Postgres queries — subscriptions table."""
from __future__ import annotations

import asyncpg


async def get_user_is_paid(conn: asyncpg.Connection) -> bool:
    """Return True iff the current user has a subscription with plan != 'free'.

    Relies on RLS: the conn must be user-scoped via current_setting('app.current_user_id').
    A missing subscription row is treated as 'free' (returns False), so newly
    registered users start unpaid until a subscription row is created.
    """
    plan = await conn.fetchval("SELECT plan FROM subscriptions LIMIT 1")
    return plan is not None and plan != "free"
