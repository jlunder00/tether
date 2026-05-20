"""Agent pool background refill loop — keeps warm queues topped up."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .pool import Pool

log = logging.getLogger(__name__)


class RefillLoop:
    """Background task that fills warm queues to target_depth_per_hash.

    A single loop walks all registered hashes rather than one task per hash —
    simpler to test and reason about, adequate for the target scale.
    """

    def __init__(self, pool: Pool) -> None:
        self._pool = pool
        # options_hash → options dict
        self._registry: dict[str, dict[str, Any]] = {}
        self._hint_event = asyncio.Event()
        self._running = False
        self._task: asyncio.Task | None = None

    def register(self, options_hash: str, options: dict[str, Any]) -> None:
        """Register a hash for periodic refill.  Idempotent."""
        self._registry[options_hash] = options

    async def hint(self, options_hash: str, options: dict[str, Any]) -> None:
        """Signal that a user will likely need a subprocess soon.

        Registers the hash and triggers an immediate refill cycle.
        """
        self.register(options_hash, options)
        self._hint_event.set()
        # Run one fill cycle immediately for this hash
        deficit = self._deficit(options_hash)
        for _ in range(deficit):
            asyncio.create_task(
                self._pool._try_inject_warm(options_hash, options)
            )

    async def run_once(self) -> None:
        """Run one full refill cycle across all registered hashes."""
        for options_hash, options in list(self._registry.items()):
            deficit = self._deficit(options_hash)
            for _ in range(deficit):
                accepted = await self._pool._try_inject_warm(options_hash, options)
                if not accepted:
                    log.debug("Capacity full during refill for hash %s", options_hash)
                    break

    async def run(self) -> None:
        """Continuous refill loop — run as an asyncio task."""
        self._running = True
        log.info("RefillLoop started")
        try:
            while self._running:
                await self.run_once()
                # Wait for poll interval, but wake early on hint
                try:
                    await asyncio.wait_for(
                        self._wait_for_hint(),
                        timeout=self._pool.config.refill_poll_interval,
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            log.info("RefillLoop cancelled")
            raise

    async def _wait_for_hint(self) -> None:
        await self._hint_event.wait()
        self._hint_event.clear()

    def _deficit(self, options_hash: str) -> int:
        """How many subprocesses need to be spawned to hit target_depth."""
        target = self._pool.config.target_depth_per_hash
        warm = self._pool.warm_count(options_hash)
        warming = self._pool.warming_count(options_hash)
        return max(0, target - warm - warming)

    def start(self) -> asyncio.Task:
        """Start the loop as a background asyncio task."""
        self._task = asyncio.create_task(self.run(), name="agent-pool-refill")
        return self._task

    def stop(self) -> None:
        """Cancel the background task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
