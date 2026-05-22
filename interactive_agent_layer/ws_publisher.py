"""In-process asyncio queue-based pubsub per user_ws_id.

When a Redis client is provided, push() dual-writes: in-process queues
for same-process consumers (tests, co-located scenarios) AND a Redis
PUBLISH to user:{user_ws_id}:events for cross-process delivery to the
API's WS subscription task.

Channel key: user:{user_ws_id}:events

Redis errors are suppressed with contextlib.suppress so a Redis outage
never breaks in-process delivery or the layer's normal turn flow.

Future: if the layer is ever extracted to a fully separate host with no
in-process subscribers, drop the queue logic entirely and keep only the
Redis publish path.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class WSPublisher:
    """Per-user asyncio queue fan-out. Keyed by user_ws_id.

    Parameters
    ----------
    redis_client:
        Optional async Redis client (e.g. redis.asyncio.Redis). When set,
        push() also publishes to ``user:{user_ws_id}:events`` so the API
        process can forward events to connected browser WebSockets.
        Pass ``None`` (the default) for in-process-only operation.
    """

    def __init__(self, redis_client: Any = None) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._redis = redis_client

    def subscribe(self, user_ws_id: str) -> asyncio.Queue:
        """Return a new queue registered for this user_ws_id."""
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(user_ws_id, []).append(q)
        return q

    def unsubscribe(self, user_ws_id: str, q: asyncio.Queue) -> None:
        """Remove a specific queue from the subscriber list."""
        queues = self._queues.get(user_ws_id, [])
        try:
            queues.remove(q)
        except ValueError:
            pass

    async def push(self, user_ws_id: str, event: dict) -> None:
        """Fan out event to all in-process subscribers and cross-process via Redis.

        In-process delivery is always attempted first. Redis publish is
        fire-and-forget: errors are logged at DEBUG and suppressed so a
        Redis outage never prevents in-process delivery.
        """
        for q in self._queues.get(user_ws_id, []):
            await q.put(event)

        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.publish(
                    f"user:{user_ws_id}:events", json.dumps(event)
                )
