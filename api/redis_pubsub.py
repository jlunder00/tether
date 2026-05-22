"""Redis pub/sub helpers for cross-process event delivery.

Architecture
------------
The interactive-agent-layer (port 5003) and the API (port 8000) run as
separate supervisord programs in the same container. The layer's
WSPublisher dual-writes events to both in-process asyncio queues and a
Redis channel. This module provides the subscriber side: per connected
WebSocket, a background task subscribes to the user's channel and
forwards events as WS frames to the browser.

Channel key: ``user:{user_id}:events``

Graceful degradation
--------------------
If ``REDIS_URL`` is not set, the subscription task is never started and
the app runs without cross-process event delivery. Background events
(trial_usage_update, Beacon notifications) won't reach connected
browsers until Redis is configured — but the app starts and serves
requests normally.

Future migration to managed Redis
----------------------------------
Change ``REDIS_URL`` from ``redis://localhost:6379`` (supervisord Redis)
to a managed Upstash/ElastiCache URL with TLS
(``rediss://user:pass@host:port``). No code changes needed — the Redis
client handles auth and TLS from the URL scheme.

Fly provisioning (when ready)
------------------------------
  fly redis create --name tether-redis --org personal
  fly secrets set REDIS_URL="<upstash-url>" --app tether-prod
  fly secrets set REDIS_URL="<upstash-url>" --app tether-dev

Until then the supervisord ``[program:redis]`` stanza in supervisord.conf
provides a local Redis instance with ``REDIS_URL=redis://localhost:6379``.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Any

from shared.redis_channels import channel_for  # noqa: F401 — re-exported for API consumers

logger = logging.getLogger(__name__)


def get_redis_url() -> str | None:
    """Return REDIS_URL from environment, or None if unset."""
    return os.environ.get("REDIS_URL") or None


async def subscribe_and_forward(
    websocket: Any,
    user_id: str,
    *,
    redis_url: str | None = None,
    server: Any = None,  # fakeredis FakeServer for testing
) -> None:
    """Subscribe to user:{user_id}:events and forward events to websocket.

    Runs until cancelled (typically when the WS disconnects). Each event
    published to the channel is deserialized and sent as a JSON WS frame.
    WS send failures are swallowed so a disconnected client doesn't crash
    the subscriber task.

    Parameters
    ----------
    websocket:
        An open WebSocket with a ``send_json(dict)`` async method.
    user_id:
        The authenticated user whose channel to subscribe to.
    redis_url:
        Redis connection URL. Defaults to ``get_redis_url()``.
    server:
        Optional fakeredis FakeServer — used in tests to share state
        between publisher and subscriber without a real Redis process.
    """
    import redis.asyncio as aioredis

    url = redis_url or get_redis_url()
    if url is None and server is None:
        logger.warning(
            "subscribe_and_forward: REDIS_URL not set — "
            "background events will not reach user_id=%s",
            user_id,
        )
        # Block forever (keeps caller's task alive until cancelled)
        await asyncio.Future()
        return

    # Build client: real Redis from URL, or fakeredis via server param
    if server is not None:
        import fakeredis.aioredis as faioredis
        client: Any = faioredis.FakeRedis(server=server)
    else:
        client = aioredis.from_url(url)

    pubsub = client.pubsub()
    channel = channel_for(user_id)
    await pubsub.subscribe(channel)
    logger.debug(
        "subscribe_and_forward: subscribed to %s for user_id=%s", channel, user_id
    )
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                event = json.loads(message["data"])
                await websocket.send_json(event)
            except Exception as exc:
                logger.debug(
                    "subscribe_and_forward: WS send failed user_id=%s: %s",
                    user_id, exc,
                )
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
        with contextlib.suppress(Exception):
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await client.aclose()
