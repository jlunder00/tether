"""Internal API routes — not mounted in OpenAPI schema.

Called by Fly.io cron machines. All endpoints require X-Internal-Token header.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import secrets

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from bot.message_handler import check_followups
from bot import notify

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


async def _check_anchor_transitions(pool, user_id: str, dispatch_fn) -> None:
    """Check and fire any due anchor transitions for the given user."""
    from datetime import datetime
    from bot.handler_utils import get_current_anchor, is_anchor_active
    from bot.message_handler import _get_anchors_and_plan, _init_followup_states
    from db.pg_queries.anchors import get_anchors
    from bot.anchor_trigger import trigger_anchor

    try:
        from datetime import date as _date
        today = str(_date.today())
        anchors, plan = await _get_anchors_and_plan(pool, user_id, today)
        current_anchor = get_current_anchor(anchors)
        if current_anchor and is_anchor_active(current_anchor):
            if plan and current_anchor["id"] in plan.get("anchors", {}):
                now = datetime.now()
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
    except Exception as e:
        logger.warning("Anchor transition check failed for user %s: %s", user_id, e)


async def _run_notification_check(pool, ws_manager) -> None:
    """For each linked user: check anchor transitions, follow-ups, meeting events."""
    if pool is None:
        logger.warning("_run_notification_check: no pool available, skipping")
        return

    try:
        users = await _get_all_linked_users(pool)
    except Exception as e:
        logger.error("_run_notification_check: failed to load users: %s", e)
        return

    for user in users:
        user_id = str(user["id"])
        try:
            dispatch_fn = functools.partial(
                notify.dispatch, pool=pool, ws_manager=ws_manager
            )
            await _check_anchor_transitions(pool, user_id, dispatch_fn)
        except Exception as e:
            logger.warning("Anchor check failed for user %s: %s", user_id, e)

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
            await check_followups(pool, user_id, send_fn)
        except Exception as e:
            logger.warning("Followup check failed for user %s: %s", user_id, e)

        try:
            from tether_premium.bot.scheduling.events import drain_meeting_events

            async def _notify_meeting_send(text, uid=user_id):
                await notify.dispatch(
                    uid,
                    "meeting_event",
                    text,
                    pool,
                    priority="important",
                    ws_manager=ws_manager,
                )

            meeting_send = lambda text, uid=user_id: asyncio.ensure_future(
                _notify_meeting_send(text, uid)
            )
            await drain_meeting_events(pool=pool, user_id=user_id, send_fn=meeting_send)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Meeting event drain failed for user %s: %s", user_id, e)


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
