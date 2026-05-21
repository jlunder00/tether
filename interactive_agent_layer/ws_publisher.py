"""In-process asyncio queue-based pubsub per user_ws_id.

v1 — replace with Redis pubsub when extracted to its own service.
"""
from __future__ import annotations

import asyncio


class WSPublisher:
    """Per-user asyncio queue fan-out. Keyed by user_ws_id."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}

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
        """Fan out event to all subscribers for this user_ws_id."""
        for q in self._queues.get(user_ws_id, []):
            await q.put(event)
