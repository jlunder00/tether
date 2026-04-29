"""Async Postgres queries — subscriptions table."""
from __future__ import annotations

import asyncpg


async def get_user_is_paid(conn: asyncpg.Connection) -> bool:
    """Return True iff the current user has an active subscription with plan != 'free'.

    Relies on RLS: the conn must be user-scoped via current_setting('app.current_user_id').
    Raises RuntimeError if the RLS context is not set, so a future caller that
    forgets to pass a user-scoped conn fails loudly instead of silently marking
    every user as unpaid.

    A row with status != 'active' (e.g. 'cancelled', 'past_due') does not grant
    paid access — billing state, not the plan column alone, drives is_paid.
    A missing row is treated as free.
    """
    rls_user_id = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)"
    )
    if not rls_user_id:
        raise RuntimeError(
            "get_user_is_paid called without a user-scoped connection "
            "(app.current_user_id not set)"
        )
    plan = await conn.fetchval(
        "SELECT plan FROM subscriptions WHERE status = 'active' LIMIT 1"
    )
    # plan is None when no active row exists (legitimate free state).
    return plan is not None and plan != "free"
