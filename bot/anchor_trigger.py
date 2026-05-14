#!/usr/bin/env python3
"""Cron-invoked: sends anchor transition message to Telegram.

Phase C refactor — internal endpoint migration:
  - trigger_anchor signature changed to keyword-only args:
    trigger_anchor(anchor_id, *, pool, user_id, dispatch_fn)
  - dispatch_fn is now called with notify-style kwargs (user_id=, notification_type=,
    text=, priority=, thread_key=) rather than a bare string.
  - main() and _run_standalone() removed — invocation now handled by the
    internal API endpoint (api/routes/internal.py).

DEPRECATED: The standalone CLI entry point has been removed. Use the internal
HTTP endpoint POST /api/internal/notifications/check instead.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Callable, Awaitable

from bot.plan_reader import load_context, load_plan
from bot.prompt_builder import build_anchor_prompt
from bot.message_handler import call_claude
import db.postgres as pg
from db.pg_queries import anchors as anchors_module

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


async def trigger_anchor(
    anchor_id: str,
    *,
    pool,
    user_id: str,
    dispatch_fn: Callable[..., Awaitable[None]],
) -> None:
    """Generate and send an anchor transition message for the given user.

    Args:
        anchor_id: the anchor being triggered (e.g. 'grind_am').
        pool: asyncpg connection pool (already open).
        user_id: Tether user UUID string.
        dispatch_fn: async callable accepting notify-style keyword args:
            user_id, notification_type, text, priority, thread_key.
    """

    async with pg.get_conn(pool, user_id) as conn:
        anchors_list = await anchors_module.get_anchors(conn)

    anchors = {a["id"]: a for a in anchors_list}
    if anchor_id not in anchors:
        logger.error("Unknown anchor: %s", anchor_id)
        return

    anchor = anchors[anchor_id]
    plan = await load_plan(pool, user_id)
    context = await load_context(pool, user_id)

    anchor_plan = plan.anchors.get(anchor_id)
    if anchor_plan is None:
        return  # anchor not scheduled today — skip silently

    prompt = build_anchor_prompt(
        templates_dir=PROMPTS_DIR,
        anchor_id=anchor_id,
        anchor_name=anchor["name"],
        anchor_plan=anchor_plan,
        day_plan=plan,
        context=context,
    )

    message = await call_claude(prompt)
    await dispatch_fn(
        user_id=user_id,
        notification_type="anchor_ping",
        text=message,
        priority="important",
        thread_key=f"anchor:{anchor_id}:{date.today()}",
    )
