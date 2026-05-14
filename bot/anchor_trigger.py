#!/usr/bin/env python3
"""Cron-invoked: sends anchor transition message to Telegram.

Phase 1 refactor — per-user Telegram migration:
  - Accepts (pool, user_id, dispatch_fn) instead of reading globals.
  - Replaces subprocess claude CLI with call_claude() from message_handler.
  - Removes config.yaml read and TETHER_USER_ID env var requirement.
  - Removes send_telegram() / direct bot_token / chat_id references.

The standalone CLI entry point (main()) still works: it bootstraps its own
pool, loads the vault key, fetches credentials from DB, and invokes
trigger_anchor(pool, user_id, dispatch_fn, anchor_id).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
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
    pool,
    user_id: str,
    dispatch_fn: Callable[[str], Awaitable[None]],
    anchor_id: str,
) -> None:
    """Generate and send an anchor transition message for the given user.

    Args:
        pool: asyncpg connection pool (already open).
        user_id: Tether user UUID string.
        dispatch_fn: async callable that sends a text message to the user,
            e.g. ``lambda msg: _send_telegram(token, chat_id, msg)``.
        anchor_id: the anchor being triggered (e.g. 'grind_am').
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
    await dispatch_fn(message)


async def _run_standalone(anchor_id: str) -> None:
    """Bootstrap credentials from DB and call trigger_anchor.

    Used by the cron-invoked CLI entry point. No env vars needed —
    vault key comes from config, token from telegram_connections.
    """
    import db.postgres as pg
    import db.pg_auth_queries as pg_auth_queries
    from bot.message_handler import _fetch_poll_credentials, _send_telegram
    from bot.message_handler import tether_config
    from cryptography.fernet import Fernet

    vault_key_str = tether_config.get("vault.key")
    if not vault_key_str:
        logger.error("vault.key not configured — cannot decrypt bot token")
        sys.exit(1)

    fernet = Fernet(
        vault_key_str.encode() if isinstance(vault_key_str, str) else vault_key_str
    )

    pool = await pg.create_pool()
    try:
        credentials = await _fetch_poll_credentials(pool, fernet)
        if credentials is None:
            logger.error(
                "No per-user bot token in DB. "
                "Run scripts/migrate_telegram_to_per_user.py first."
            )
            sys.exit(1)

        token, chat_id, user_id = credentials

        async def dispatch(msg: str) -> None:
            _send_telegram(token, chat_id, msg)

        await trigger_anchor(pool, user_id, dispatch, anchor_id)
    finally:
        await pool.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Tether anchor trigger")
    parser.add_argument("anchor_id", help="Anchor to trigger (e.g. grind_am)")
    args = parser.parse_args()
    asyncio.run(_run_standalone(args.anchor_id))


if __name__ == "__main__":
    main()
