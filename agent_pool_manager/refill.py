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
        # options_hash → user_id (stored alongside options for key injection)
        self._user_ids: dict[str, str] = {}
        self._hint_event = asyncio.Event()
        self._running = False
        self._task: asyncio.Task | None = None

    def register(
        self,
        options_hash: str,
        options: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> None:
        """Register a hash for periodic refill.  Idempotent."""
        already_known = options_hash in self._registry
        self._registry[options_hash] = options
        if user_id:  # truthy: excludes None and "" to prevent UUID parse errors
            self._user_ids[options_hash] = user_id
        log.info(
            "refill.register options_hash=%s already_known=%s registry_size=%d",
            options_hash, already_known, len(self._registry),
        )

    async def hint(
        self,
        options_hash: str,
        options: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> None:
        """Signal that a user will likely need a subprocess soon.

        Registers the hash and triggers an immediate refill cycle.
        """
        self.register(options_hash, options, user_id=user_id)
        self._hint_event.set()
        # Run one fill cycle immediately for this hash
        deficit = self._deficit(options_hash)
        log.info(
            "refill.hint options_hash=%s deficit=%d target_depth=%d"
            " warm=%d warming=%d",
            options_hash,
            deficit,
            self._pool.config.target_depth_per_hash,
            self._pool.warm_count(options_hash),
            self._pool.warming_count(options_hash),
        )
        for _ in range(deficit):
            asyncio.create_task(
                self._pool._try_inject_warm(options_hash, options, user_id=user_id)
            )

    async def run_once(self) -> None:
        """Run one full refill cycle across all registered hashes."""
        for options_hash, options in list(self._registry.items()):
            # Defensive: normalise "" → None so create_key never receives an
            # empty UUID regardless of how the value entered _user_ids.
            user_id = self._user_ids.get(options_hash) or None
            deficit = self._deficit(options_hash)
            if deficit > 0:
                log.info(
                    "refill.run_once options_hash=%s deficit=%d warm=%d warming=%d",
                    options_hash, deficit,
                    self._pool.warm_count(options_hash),
                    self._pool.warming_count(options_hash),
                )
            for _ in range(deficit):
                accepted = await self._pool._try_inject_warm(
                    options_hash, options, user_id=user_id
                )
                if not accepted:
                    log.info(
                        "refill.capacity_full options_hash=%s — breaking refill cycle",
                        options_hash,
                    )
                    break

        # TTL sweep — evict any stale home dir assignments each cycle.
        if self._pool._home_pool is not None:
            await self._pool._home_pool.sweep()

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
