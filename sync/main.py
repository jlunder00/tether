"""Entry point for the tether-sync worker.

Start with:
    python -m sync

The worker:
  1. Connects to Postgres via DATABASE_URL
  2. Registers all integration providers with the registry
  3. Starts the LISTEN loop (PG LISTEN integration_sync)
  4. Starts cron jobs (watch renewal, token refresh)
  5. Runs until SIGTERM/SIGINT, then shuts down cleanly
"""
from __future__ import annotations

import asyncio
import logging
import signal

import db.postgres as pg
from sync.worker import SyncWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _register_providers() -> None:
    """Register all known integration providers with the registry.

    Premium providers register themselves via the tether_premium plugin hook
    (try/except import), following the same pattern as api/main.py.
    """
    import integrations.registry as registry
    from integrations.google_calendar.auth import GoogleCalendarAuth
    from integrations.google_calendar.sync import GoogleCalendarSync
    registry.register(
        "google_calendar",
        oauth_cls=GoogleCalendarAuth,
        sync_cls=GoogleCalendarSync,
    )

    # Premium provider hook
    try:
        from tether_premium.integrations.register import register_premium_providers
        register_premium_providers(registry)
    except ImportError:
        pass


async def _main() -> None:
    _register_providers()

    pool = await pg.create_pool()
    worker = SyncWorker(pool)

    loop = asyncio.get_running_loop()

    def _handle_signal():
        logger.info("Shutdown signal received")
        asyncio.create_task(worker.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    logger.info("Starting tether-sync worker")
    await worker.start()
    await worker.wait()

    await pg.close_pool()
    logger.info("tether-sync worker stopped")


if __name__ == "__main__":
    asyncio.run(_main())
