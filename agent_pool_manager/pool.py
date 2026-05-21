"""Agent pool core — Pool class, Subprocess dataclass, lifecycle management."""
from __future__ import annotations

import asyncio
import datetime
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import ClaudeAgentOptions, ResultMessage

from .config import AgentPoolConfig

log = logging.getLogger(__name__)


class PoolExhausted(Exception):
    """Raised when no warm subprocess becomes available within the timeout."""


def _extract_pid(client: ClaudeSDKClient) -> int | None:
    """Best-effort PID extraction from the SDK client's transport."""
    try:
        transport = client._transport
        proc = getattr(transport, "_process", None) if transport is not None else None
        return proc.pid if proc is not None else None
    except Exception:
        return None


@dataclass
class Subprocess:
    """Tracks one ClaudeSDKClient instance and its metadata."""

    proc: ClaudeSDKClient
    options_hash: str
    options: dict[str, Any]
    spawned_at: float = field(default_factory=time.monotonic)
    primed_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    in_use: bool = False

    def is_expired(self, max_age_seconds: int) -> bool:
        return (time.monotonic() - self.spawned_at) > max_age_seconds


class Pool:
    """In-memory pool of warm ClaudeSDKClient subprocesses.

    Partitioned by ``options_hash``.  TTL draining happens on acquire
    (drain-on-touch), not via a background timer.
    """

    def __init__(self, config: AgentPoolConfig) -> None:
        self.config = config
        # warm queue per options_hash
        self._warm: dict[str, asyncio.Queue[Subprocess]] = {}
        # active (handed-out) subprocesses keyed by handle_id
        self._active: dict[str, Subprocess] = {}
        # count of currently-spawning tasks per options_hash
        self._warming: dict[str, int] = {}
        # cached options payload per options_hash (for refill)
        self._options_cache: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(
        self,
        options_hash: str,
        options: dict[str, Any],
        timeout: float | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Hand out a warm subprocess for the given options_hash.

        Blocks until one is available or ``timeout`` seconds elapses.
        Drains expired entries before returning.

        Returns ``(handle_id, metadata)`` where metadata contains
        ``subprocess_pid`` and ``ready_at``.

        Raises :exc:`PoolExhausted` if timeout is exceeded.
        """
        if timeout is None:
            timeout = self.config.acquire_default_timeout

        self._options_cache[options_hash] = options
        deadline = time.monotonic() + timeout
        queue = self._get_or_create_queue(options_hash)

        exhausted = PoolExhausted(
            f"No warm subprocess for hash {options_hash!r} within {timeout}s"
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise exhausted

            try:
                sub = queue.get_nowait()
            except asyncio.QueueEmpty:
                # Wait for a warm item to appear, then re-check the deadline.
                try:
                    sub = await asyncio.wait_for(queue.get(), timeout=min(remaining, 0.1))
                except asyncio.TimeoutError:
                    continue

            # Drain expired entries
            if sub.is_expired(self.config.max_age_seconds):
                log.debug("Draining expired subprocess for hash %s", options_hash)
                asyncio.create_task(self._terminate(sub))
                continue

            # Hand it out
            handle_id = str(uuid.uuid4())
            sub.in_use = True
            sub.last_used_at = time.monotonic()
            async with self._lock:
                self._active[handle_id] = sub

            meta = {
                "subprocess_pid": _extract_pid(sub.proc),
                "ready_at": datetime.datetime.utcnow().isoformat() + "Z",
            }
            return handle_id, meta

    async def release(self, handle_id: str, reusable: bool = False) -> None:
        """Release a handle.

        ``reusable=True`` → return subprocess to warm queue (caller asserts
        no sensitive history).  ``reusable=False`` (default) → terminate.
        """
        async with self._lock:
            sub = self._active.pop(handle_id, None)
        if sub is None:
            return

        sub.in_use = False
        sub.last_used_at = time.monotonic()

        if reusable and not sub.is_expired(self.config.max_age_seconds):
            queue = self._get_or_create_queue(sub.options_hash)
            await queue.put(sub)
            log.debug("Subprocess returned to warm queue for hash %s", sub.options_hash)
        else:
            await self._terminate(sub)

    async def interrupt(self, handle_id: str) -> None:
        """Send an interrupt to the active subprocess for the given handle."""
        async with self._lock:
            sub = self._active.get(handle_id)
        if sub is None:
            raise KeyError(f"No active handle {handle_id!r}")
        await sub.proc.interrupt()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def warm_count(self, options_hash: str) -> int:
        """Current warm queue depth for this options_hash."""
        q = self._warm.get(options_hash)
        return q.qsize() if q else 0

    def active_count(self) -> int:
        return len(self._active)

    def warming_count(self, options_hash: str | None = None) -> int:
        if options_hash is not None:
            return self._warming.get(options_hash, 0)
        return sum(self._warming.values())

    def total_count(self) -> int:
        """Total subprocesses: warm + active + warming."""
        warm = sum(q.qsize() for q in self._warm.values())
        return warm + self.active_count() + self.warming_count()

    def status(self) -> dict[str, Any]:
        """Pool-wide status snapshot."""
        partitions: dict[str, dict[str, int]] = {
            h: {"warm": q.qsize(), "warming": self._warming.get(h, 0)}
            for h, q in self._warm.items()
        }
        for sub in self._active.values():
            slot = partitions.setdefault(sub.options_hash, {"warm": 0, "warming": 0})
            slot["active"] = slot.get("active", 0) + 1

        return {
            "partitions": partitions,
            "total_warm": sum(p["warm"] for p in partitions.values()),
            "total_active": self.active_count(),
            "total_warming": self.warming_count(),
            "capacity_total": self.config.capacity_total,
        }

    # ------------------------------------------------------------------
    # Internal helpers — also used by RefillLoop and tests
    # ------------------------------------------------------------------

    async def _inject_warm(self, options_hash: str, options: dict[str, Any]) -> None:
        """Spawn, prime, and push one subprocess to the warm queue.

        Used directly by RefillLoop and by tests via FakeClient patch.
        Silently no-ops at capacity.
        """
        if not await self._try_inject_warm(options_hash, options):
            log.debug("Capacity full — skipping inject for hash %s", options_hash)

    async def _try_inject_warm(self, options_hash: str, options: dict[str, Any]) -> bool:
        """Attempt to spawn-and-prime one subprocess.

        Returns True if spawned, False if at capacity.
        """
        async with self._lock:
            if self.total_count() >= self.config.capacity_total:
                return False
            self._warming[options_hash] = self._warming.get(options_hash, 0) + 1

        try:
            sub = await self._spawn_and_prime(options_hash, options)
        finally:
            async with self._lock:
                self._warming[options_hash] = max(
                    0, self._warming.get(options_hash, 1) - 1
                )

        queue = self._get_or_create_queue(options_hash)
        await queue.put(sub)
        self._options_cache[options_hash] = options
        log.debug("Primed subprocess ready for hash %s", options_hash)
        return True

    async def _spawn_and_prime(
        self, options_hash: str, options: dict[str, Any]
    ) -> Subprocess:
        """Spawn a ClaudeSDKClient, connect, and send the priming prompt."""
        sdk_options = self._build_sdk_options(options)
        client = ClaudeSDKClient(options=sdk_options)
        await client.connect()

        # Prime: send a cheap prompt so the subprocess pays its init cost now
        try:
            await asyncio.wait_for(
                self._do_prime(client),
                timeout=self.config.prime_timeout_seconds,
            )
        except asyncio.TimeoutError:
            log.warning("Priming timed out for hash %s — keeping unprimed client", options_hash)

        now = time.monotonic()
        return Subprocess(
            proc=client,
            options_hash=options_hash,
            options=options,
            spawned_at=now,
            primed_at=now,
        )

    @staticmethod
    async def _do_prime(client: ClaudeSDKClient) -> None:
        """Send the priming prompt and drain the response."""
        await client.query("respond with only 'ready'")
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                break

    @staticmethod
    def _build_sdk_options(options: dict[str, Any]) -> ClaudeAgentOptions:
        """Convert the options dict to ClaudeAgentOptions, ignoring unknown keys."""
        known = {f for f in dir(ClaudeAgentOptions) if not f.startswith("_")}
        filtered = {k: v for k, v in options.items() if k in known}
        return ClaudeAgentOptions(**filtered)

    def _get_or_create_queue(self, options_hash: str) -> asyncio.Queue[Subprocess]:
        if options_hash not in self._warm:
            self._warm[options_hash] = asyncio.Queue()
        return self._warm[options_hash]

    @staticmethod
    async def _terminate(sub: Subprocess) -> None:
        try:
            await sub.proc.disconnect()
        except Exception:
            pass
