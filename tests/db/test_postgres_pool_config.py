"""Unit tests for create_pool() configuration — no live Postgres required.

Regression coverage for the prod DB-quota fix: managed Postgres only suspends
compute at zero open connections. With min_size=2, every prod process (api,
bot, mcp, agent_pool_manager) held connections open 24/7, so compute never
suspended and the monthly compute-time quota was exhausted continuously.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

import db.postgres as postgres_module


@pytest.fixture(autouse=True)
def reset_pool_singleton():
    """create_pool() caches into a module-level global; reset around each test."""
    postgres_module._pool = None
    yield
    postgres_module._pool = None


@pytest.fixture
def fake_dsn():
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake/db"}):
        yield


@pytest.mark.asyncio
async def test_create_pool_uses_min_size_zero(fake_dsn):
    """min_size=0 lets the pool release all connections when idle, so managed
    Postgres compute can suspend between requests instead of running 24/7."""
    with patch(
        "db.postgres.asyncpg.create_pool", new=AsyncMock(return_value="fake-pool")
    ) as mock_create:
        await postgres_module.create_pool()

    assert mock_create.call_args.kwargs["min_size"] == 0


@pytest.mark.asyncio
async def test_create_pool_sets_finite_max_inactive_connection_lifetime(fake_dsn):
    """A finite lifetime ensures idle connections are actually dropped instead
    of lingering, which is what allows compute to suspend."""
    with patch(
        "db.postgres.asyncpg.create_pool", new=AsyncMock(return_value="fake-pool")
    ) as mock_create:
        await postgres_module.create_pool()

    lifetime = mock_create.call_args.kwargs.get("max_inactive_connection_lifetime")
    assert lifetime is not None
    assert 0 < lifetime <= 300


@pytest.mark.asyncio
async def test_create_pool_preserves_max_size_and_timeout(fake_dsn):
    """Guard against accidental regression of unrelated pool params."""
    with patch(
        "db.postgres.asyncpg.create_pool", new=AsyncMock(return_value="fake-pool")
    ) as mock_create:
        await postgres_module.create_pool()

    assert mock_create.call_args.kwargs["max_size"] == 10
    assert mock_create.call_args.kwargs["command_timeout"] == 30


@pytest.mark.asyncio
async def test_create_pool_is_singleton(fake_dsn):
    """create_pool() should only construct the pool once and cache it."""
    with patch(
        "db.postgres.asyncpg.create_pool", new=AsyncMock(return_value="fake-pool")
    ) as mock_create:
        first = await postgres_module.create_pool()
        second = await postgres_module.create_pool()

    assert first is second
    mock_create.assert_awaited_once()
