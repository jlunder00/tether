"""Isolated per-subprocess home directory pool.

Each subprocess gets its own ``$HOME`` to eliminate ``~/.claude.json`` lock
contention when two subprocesses spawn simultaneously.  Dirs are pre-created
at pool startup and reset to a template state before each assignment so stale
CLI state from a previous subprocess never bleeds into the next one.

Design notes:
- Dirs are never deleted during normal operation — only reset.
- Reset (``shutil.rmtree`` + ``shutil.copytree``) runs in a thread-pool
  executor so it does not block the asyncio event loop during spawn.
- TTL sweep evicts stale assignments (e.g. a subprocess that was lost
  without going through ``_terminate``).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_pool_manager.config import AgentPoolConfig

log = logging.getLogger(__name__)


def _reset_home(home: Path, template: Path | None) -> None:
    """Synchronous reset called from a thread executor.

    Removes all content in *home* then either copies *template* in (if it
    exists) or leaves *home* as an empty directory.
    """
    # Wipe and recreate so the dir is empty/fresh regardless of template.
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True, exist_ok=True)
    if template is not None and template.is_dir():
        # copytree requires the destination not to exist; use dirs_exist_ok
        # (Python 3.8+) so we can copy *into* the already-created home dir.
        shutil.copytree(str(template), str(home), dirs_exist_ok=True)


class HomeDirPool:
    """Pool of isolated home directories for agent subprocesses.

    Call ``await initialize()`` once before first use.
    Call ``await acquire()`` to obtain a home dir for a new subprocess.
    Call ``release(path)`` when the subprocess terminates.
    Call ``await sweep()`` periodically (from RefillLoop.run_once) to evict
    stale assignments that were never released.
    """

    def __init__(self, config: AgentPoolConfig) -> None:
        self._config = config
        self._base = Path(config.home_dir_base)
        template_path = Path(config.home_dir_template)
        self._template: Path | None = template_path if template_path.is_dir() else None
        self._dirs: list[Path] = []
        self._available: asyncio.Queue[Path] = asyncio.Queue()
        # str(path) → expiry timestamp (time.monotonic)
        self._checked_out: dict[str, float] = {}

    async def initialize(self) -> None:
        """Create home dirs and seed from template.  Idempotent on re-call."""
        count = self._config.capacity_total
        self._base.mkdir(parents=True, exist_ok=True)

        # Re-discover template now (it may have been created since __init__)
        template_path = Path(self._config.home_dir_template)
        self._template = template_path if template_path.is_dir() else None

        for i in range(count):
            home = self._base / f"home-{i}"
            home.mkdir(parents=True, exist_ok=True)
            # Skip reset for dirs currently checked out by a live subprocess —
            # wiping them would corrupt the running CLI process's HOME.
            if str(home) not in self._checked_out:
                # Seed from template in executor to avoid blocking the loop.
                await asyncio.to_thread(_reset_home, home, self._template)
            if home not in self._dirs:
                self._dirs.append(home)
            # Populate the available queue; clear first to avoid duplication on re-init.

        # Rebuild _available from dirs not currently checked out.
        while not self._available.empty():
            try:
                self._available.get_nowait()
            except asyncio.QueueEmpty:
                break
        checked_out_paths = set(self._checked_out.keys())
        for home in self._dirs:
            if str(home) not in checked_out_paths:
                self._available.put_nowait(home)

        log.info(
            "home_pool.initialized count=%d template=%s available=%d",
            count,
            self._template,
            self._available.qsize(),
        )

    async def acquire(self) -> Path:
        """Return a home dir, reset to template state.

        Blocks (up to the caller's timeout) if the pool is exhausted.
        Raises ``asyncio.QueueEmpty`` if called with nowait and no dirs are
        available — callers should use ``asyncio.wait_for`` for timeouts.
        """
        home = await self._available.get()
        await asyncio.to_thread(_reset_home, home, self._template)
        # Use 2× subprocess max_age as home TTL so sweep never evicts a home
        # whose subprocess might still be running (drain-on-touch retirement
        # means a subprocess can live past its nominal max_age).
        expiry = time.monotonic() + self._config.max_age_seconds * 2
        self._checked_out[str(home)] = expiry
        log.debug("home_pool.acquired path=%s", home)
        return home

    def release(self, home: Path) -> None:
        """Return *home* to the available queue.  Idempotent."""
        key = str(home)
        if key not in self._checked_out:
            # Already released or never acquired — silently ignore.
            return
        self._checked_out.pop(key)
        self._available.put_nowait(home)
        log.debug("home_pool.released path=%s", home)

    async def sweep(self) -> None:
        """Evict stale assignments that were never released (TTL-based safety net)."""
        now = time.monotonic()
        evicted = [k for k, expiry in list(self._checked_out.items()) if now > expiry]
        for key in evicted:
            self._checked_out.pop(key, None)
            path = Path(key)
            self._available.put_nowait(path)
            log.warning("home_pool.sweep_evict path=%s", path)

    def available_count(self) -> int:
        """Number of home dirs currently available (not checked out)."""
        return self._available.qsize()
