"""CoalescingBuffer for background tool action events.

Tracks recent agent_action events and coalesces repeated calls for the same
(tool_name, phrase) key within a configurable time window.
"""
from __future__ import annotations

import dataclasses
import time
import uuid
from collections.abc import Callable


@dataclasses.dataclass
class _CacheEntry:
    action_id: str
    timestamp: float


class CoalescingBuffer:
    def __init__(
        self,
        window_seconds: float = 5.0,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._window = window_seconds
        self._time_fn = time_fn or time.monotonic
        self._cache: dict[tuple[str, str], _CacheEntry] = {}

    def record(self, tool_name: str, phrase: str) -> tuple[str, bool]:
        """Record a tool call and return (action_id, coalesced).

        coalesced=True means this is a repeat within the window.
        The timestamp is updated on each hit to extend the window.
        """
        self.evict_expired()
        key = (tool_name, phrase)
        now = self._time_fn()
        entry = self._cache.get(key)
        if entry is not None and (now - entry.timestamp) < self._window:
            entry.timestamp = now
            return entry.action_id, True
        action_id = str(uuid.uuid4())
        self._cache[key] = _CacheEntry(action_id=action_id, timestamp=now)
        return action_id, False

    def evict_expired(self) -> None:
        """Remove entries older than the window.

        Call periodically to prevent unbounded growth.
        """
        now = self._time_fn()
        expired = [k for k, v in self._cache.items() if (now - v.timestamp) >= self._window]
        for k in expired:
            del self._cache[k]
