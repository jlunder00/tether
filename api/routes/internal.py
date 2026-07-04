"""Internal API routes — not mounted in OpenAPI schema.

Called by Fly.io cron machines. All endpoints require X-Internal-Token header.

Neon/idle-spin-down note
-------------------------
``_run_notification_check`` is gated by ``shared.notify_due`` — a Redis
next-due cache — so that regardless of how often this endpoint is actually
invoked (by whatever scheduler ends up calling it), it costs nothing but a
single Redis range query when no user has any anchor/followup work due
right now. See shared/notify_due.py for the full scheme. This makes the
endpoint safe to call as frequently as desired without keeping managed
Postgres (Neon) awake between real due events.

Note: this endpoint does NOT drain meeting events. `drain_meeting_events`
reads from an in-process queue owned by the BOT process
(`tether_premium.bot.scheduling.events`, populated by a WS-listener thread
started only inside `bot/message_handler.py`'s `run_polling()`) — this API
process cannot see that queue, so calling it here would always be a no-op.
Meeting-event draining happens exclusively via the bot's polling loop.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import secrets
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from bot.message_handler import check_followups
from bot import notify
from shared import notify_due

import db.postgres as pg
import db.pg_auth_queries as pg_auth_queries

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_internal_token(request: Request) -> None:
    token = request.headers.get("X-Internal-Token", "")
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403)


@router.post("/notifications/check")
async def check_notifications(request: Request, background_tasks: BackgroundTasks):
    """Called by Fly.io cron every minute. Queues notification check as BackgroundTask."""
    _verify_internal_token(request)
    pool = request.app.state.pool
    ws_manager = getattr(request.app.state, "ws_manager", None)
    background_tasks.add_task(_run_notification_check, pool, ws_manager)
    return {"status": "queued"}


@router.post("/integrations/renew-watches")
async def renew_watches(request: Request, background_tasks: BackgroundTasks):
    """Daily: renew expiring Google Calendar watch channels."""
    _verify_internal_token(request)
    background_tasks.add_task(_renew_expiring_watches, request.app.state.pool)
    return {"status": "queued"}


@router.post("/integrations/refresh-tokens")
async def refresh_tokens(request: Request, background_tasks: BackgroundTasks):
    """Hourly: refresh expiring OAuth tokens."""
    _verify_internal_token(request)
    background_tasks.add_task(_refresh_expiring_tokens, request.app.state.pool)
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# Background task implementations
# ---------------------------------------------------------------------------


async def _get_all_linked_users(pool) -> list[dict]:
    """Return all users with a telegram_chat_id linked."""
    async with pg.get_conn(pool) as conn:
        rows = await conn.fetch(
            """
            SELECT u.id, tc.telegram_chat_id
            FROM users u
            JOIN telegram_connections tc ON tc.user_id = u.id
            WHERE tc.telegram_chat_id IS NOT NULL
              AND tc.telegram_chat_id != ''
            """
        )
    return [{"id": str(r["id"]), "telegram_chat_id": r["telegram_chat_id"]} for r in rows]


async def _get_linked_users_by_id(pool, user_ids: list[str]) -> list[dict]:
    """Return linked-user rows scoped to *user_ids* — used once the Redis
    next-due gate has already told us which users are actually due, so we
    don't pay for a full-table scan on every notification-check invocation."""
    if not user_ids:
        return []
    async with pg.get_conn(pool) as conn:
        rows = await conn.fetch(
            """
            SELECT u.id, tc.telegram_chat_id
            FROM users u
            JOIN telegram_connections tc ON tc.user_id = u.id
            WHERE tc.telegram_chat_id IS NOT NULL
              AND tc.telegram_chat_id != ''
              AND u.id = ANY($1::uuid[])
            """,
            user_ids,
        )
    return [{"id": str(r["id"]), "telegram_chat_id": r["telegram_chat_id"]} for r in rows]


async def _check_anchor_transitions(pool, user_id: str, dispatch_fn) -> datetime | None:
    """Check and fire any due anchor transitions for the given user.

    Returns the next anchor-schedule boundary (start/end of a time block)
    strictly after ``now``, or ``None`` if the user has no anchors at all.
    Used by the caller to populate the Redis "anchor" due-component (see
    shared/notify_due.py) — computed from data already fetched here, no
    extra Postgres cost.
    """
    from bot.handler_utils import get_current_anchor, is_anchor_active
    from bot.message_handler import _get_anchors_and_plan, _init_followup_states
    from bot.anchor_trigger import trigger_anchor

    now = datetime.now()
    try:
        from datetime import date as _date
        today = str(_date.today())
        anchors, plan = await _get_anchors_and_plan(pool, user_id, today)
        await notify_due.set_cached_anchors(user_id, anchors)
        current_anchor = get_current_anchor(anchors)
        if current_anchor and is_anchor_active(current_anchor):
            if plan and current_anchor["id"] in plan.get("anchors", {}):
                await _init_followup_states(
                    pool, user_id, today, current_anchor["id"],
                    [t["id"] for t in plan["anchors"][current_anchor["id"]]["tasks"] if t.get("id")],
                    now,
                )
                await trigger_anchor(
                    current_anchor["id"],
                    pool=pool,
                    user_id=user_id,
                    dispatch_fn=dispatch_fn,
                )
        return notify_due.next_anchor_boundary(anchors, now)
    except Exception:
        # Broad catch pre-dates this gating change (any downstream call —
        # dispatch_fn, trigger_anchor — can raise many exception types this
        # function can't enumerate). Logged at ERROR (not WARNING) with a
        # traceback because a bug here is now indistinguishable, at the
        # call site, from "this user simply has no anchors" — the caller
        # branches on this returning None either way. This does not cause
        # under-notification (the stale cached due-time just stays in the
        # past, so the user is rechecked again next cycle), but a
        # persistent failure here should be loud in logs rather than a
        # quiet recurring WARNING.
        logger.error(
            "Anchor transition check failed for user_id=%s", user_id, exc_info=True
        )
        return None


async def _recompute_and_cache_due(
    user_id: str, anchor_next: datetime | None, followup_next: datetime | None
) -> None:
    """Write the freshest anchor/followup next-due estimates back to Redis.

    Called once per user after a real check has run — self-perpetuating:
    each real run recomputes its own future due time from data it already
    fetched, so the cache never needs a separate background refresh job.
    A ``None`` estimate means "nothing to re-check on a timer for this
    component right now" — left unset (absent from the hash) rather than
    writing a synthetic "never" value, so a future write (e.g. an anchor
    create/update, or the next anchor boundary re-triggering follow-ups)
    naturally repopulates and recomputes the combined score.
    """
    if anchor_next is not None:
        await notify_due.set_component_due(user_id, "anchor", anchor_next.timestamp())
    if followup_next is not None:
        await notify_due.set_component_due(user_id, "followup", followup_next.timestamp())


async def _run_notification_check(pool, ws_manager) -> None:
    """For each linked user: check anchor transitions and follow-ups.

    Gated by shared.notify_due: a single Redis range query decides which
    users (if any) have real work due right now. When nothing is due, this
    function returns without touching Postgres at all — see module docstring.

    Does not drain meeting events — see the module docstring's note on why
    that would always be a no-op in this (API) process.
    """
    if pool is None:
        logger.warning("_run_notification_check: no pool available, skipping")
        return

    now_ts = time.time()
    due_user_ids = await notify_due.get_due_user_ids(now_ts)

    if due_user_ids is None:
        # Redis gating unavailable — fail open to the original, unfiltered
        # behaviour rather than skipping notifications. ERROR (not WARNING):
        # a one-off blip here is harmless, but if this fires on EVERY
        # invocation it means gating has silently stopped working and the
        # endpoint is back to a full Postgres scan every call — exactly the
        # Neon-idle-spin-down regression this feature exists to prevent.
        # There's no metric/counter for "N consecutive fail-opens" yet
        # (follow-up item), so ERROR-level log visibility is the current
        # signal that something needs attention.
        logger.error(
            "notify.check_gating_unavailable — falling back to full linked-user scan"
        )
        try:
            users = await _get_all_linked_users(pool)
        except Exception as e:
            logger.error("_run_notification_check: failed to load users: %s", e)
            return
    elif not due_user_ids:
        logger.debug("notify.check_skipped_empty")
        return
    else:
        logger.info("notify.check_processed n=%d", len(due_user_ids))
        try:
            users = await _get_linked_users_by_id(pool, due_user_ids)
        except Exception as e:
            logger.error("_run_notification_check: failed to load due users: %s", e)
            return

    for user in users:
        user_id = str(user["id"])
        # No try/except here: _check_anchor_transitions already catches and
        # logs everything internally (returning None on failure) — an outer
        # catch here could never fire and was dead code.
        dispatch_fn = functools.partial(
            notify.dispatch, pool=pool, ws_manager=ws_manager
        )
        anchor_next = await _check_anchor_transitions(pool, user_id, dispatch_fn)

        followup_next: datetime | None = None
        try:
            async def _notify_send(text, uid=user_id):
                await notify.dispatch(
                    uid,
                    "task_followup",
                    text,
                    pool,
                    priority="important",
                    ws_manager=ws_manager,
                )

            send_fn = lambda text, uid=user_id: asyncio.ensure_future(_notify_send(text, uid))
            followup_next = await check_followups(pool, user_id, send_fn)
        except Exception as e:
            logger.warning("Followup check failed for user %s: %s", user_id, e)

        await _recompute_and_cache_due(user_id, anchor_next, followup_next)


async def _renew_expiring_watches(pool) -> None:
    """Renew expiring Google Calendar watch channels (daily cron)."""
    if pool is None:
        logger.warning("_renew_expiring_watches: no pool available")
        return
    try:
        from integrations.gcal.watch_manager import renew_expiring_watches
        await renew_expiring_watches(pool)
    except ImportError:
        logger.debug("_renew_expiring_watches: gcal watch manager not available")
    except Exception as e:
        logger.error("_renew_expiring_watches failed: %s", e)


async def _refresh_expiring_tokens(pool) -> None:
    """Refresh expiring OAuth tokens (hourly cron)."""
    if pool is None:
        logger.warning("_refresh_expiring_tokens: no pool available")
        return
    try:
        from integrations.oauth_refresh import refresh_all_expiring_tokens
        await refresh_all_expiring_tokens(pool)
    except ImportError:
        logger.debug("_refresh_expiring_tokens: oauth refresh not available")
    except Exception as e:
        logger.error("_refresh_expiring_tokens failed: %s", e)
