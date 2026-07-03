"""Entry point: python -m interactive_agent_layer [--host HOST] [--port PORT]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Any

import uvicorn

from interactive_agent_layer.pool_client import PoolClient
from interactive_agent_layer.server import create_app
from interactive_agent_layer.session import Layer
from interactive_agent_layer.ws_publisher import WSPublisher

logger = logging.getLogger(__name__)


async def _create_db_pool() -> Any:
    """Thin wrapper around db.postgres.create_pool() — isolated for test patching."""
    from db.postgres import create_pool

    return await create_pool()


def _get_premium_layer_kwargs(db_pool: Any) -> dict[str, Any]:
    """Return Layer kwargs (check_grant_fn/insert_grant_fn/hop_distance_fn/
    resolve_node_path_fn/resolve_conversation_scope_fn) bound to db_pool via
    tether_premium, or {} if tether_premium isn't installed.

    Mirrors the `try: import tether_premium` plugin-hook pattern used
    elsewhere (bot.agent_dispatch._dispatch_v25, tether_premium.register) —
    failure to import means the community edition runs with no gating,
    never a crash.
    """
    try:
        from tether_premium.bot.permission_grants import get_permission_grant_fns
        from tether_premium.bot.scope_grants import get_scope_fns
    except ImportError:
        logger.info(
            "interactive_agent_layer: tether_premium not installed — permission"
            " grants and scope gating are disabled (community edition)."
        )
        return {}

    check_grant_fn, insert_grant_fn = get_permission_grant_fns(db_pool)
    hop_distance_fn, resolve_node_path_fn, resolve_conversation_scope_fn = (
        get_scope_fns(db_pool)
    )
    return {
        "check_grant_fn": check_grant_fn,
        "insert_grant_fn": insert_grant_fn,
        "hop_distance_fn": hop_distance_fn,
        "resolve_node_path_fn": resolve_node_path_fn,
        "resolve_conversation_scope_fn": resolve_conversation_scope_fn,
    }


async def _build_layer(pool_client: PoolClient, publisher: WSPublisher) -> Layer:
    """Construct the production Layer, wiring premium DB-bound functions in
    when tether_premium is installed and DATABASE_URL is configured.

    Falls back to a bare Layer (no grant checks, no scope enforcement) when
    either is absent, or when DB pool creation fails — startup must never
    crash because premium wiring is unavailable; it should just run dormant,
    same as before this function existed.
    """
    db_pool = None
    if os.environ.get("DATABASE_URL"):
        try:
            db_pool = await _create_db_pool()
        except Exception:
            logger.warning(
                "interactive_agent_layer: DB pool creation failed — permission"
                " grants and scope gating will not be wired.",
                exc_info=True,
            )
            db_pool = None
    else:
        logger.info(
            "interactive_agent_layer: DATABASE_URL not set — permission grants"
            " and scope gating are disabled (dormant, backwards-compatible)."
        )

    premium_kwargs = _get_premium_layer_kwargs(db_pool) if db_pool is not None else {}
    return Layer(pool_client=pool_client, ws_publisher=publisher, **premium_kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Agent Layer service")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    redis_url = os.environ.get("REDIS_URL")
    redis_client = None
    if redis_url:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(redis_url)
        logger.info("WSPublisher: Redis dual-write enabled (%s)", redis_url)
    else:
        logger.warning(
            "WSPublisher: REDIS_URL not set — background events will not reach "
            "the API process. Set REDIS_URL=redis://localhost:6379 to enable."
        )

    publisher = WSPublisher(redis_client=redis_client)
    pool = PoolClient()
    layer = asyncio.run(_build_layer(pool, publisher))
    app = create_app(layer)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
