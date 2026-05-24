"""Tests for POST /api/internal/pool/warm endpoint.

These tests don't require DATABASE_URL — they mock auth and the pool client.
They verify:
  - Happy path returns 202 with hinted=true and options_hash
  - Pool failure still returns 202 (best-effort, never blocks FE)
  - options_hash computed correctly (same algorithm as layer._stable_options_hash)
  - Unauthenticated requests get 401
  - Unknown agent_version returns 400
"""
from __future__ import annotations

import hashlib
import json
import os

os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "dev-secret-change-in-production")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.auth import auth_dependency, create_jwt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_USER_ID = "00000000-0000-0000-0000-000000000042"
TEST_USERNAME = "warmuser"


def _stable_options_hash(options: dict) -> str:
    """Mirror of interactive_agent_layer.session._stable_options_hash."""
    canonical = json.dumps(options, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class _MockPoolClient:
    """Pool client that records hint() calls."""

    def __init__(self, *, raise_on_hint: bool = False):
        self.hint_calls: list[tuple] = []
        self._raise = raise_on_hint

    async def hint(self, user_id: str, options_hash: str, options: dict) -> None:
        self.hint_calls.append((user_id, options_hash, options))
        if self._raise:
            from agent_pool_manager.client import PoolClientError
            raise PoolClientError("pool unreachable")


def _make_mock_vault(oauth_token: str = "sk-ant-pool-warm-test"):
    """Return a mock vault whose materialize() yields CLAUDE_CODE_OAUTH_TOKEN."""
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    vault = MagicMock()

    @asynccontextmanager
    async def _materialize(user_id: str):
        yield {"CLAUDE_CODE_OAUTH_TOKEN": oauth_token}

    vault.materialize = _materialize
    return vault


def _make_app(mock_pool_client: _MockPoolClient) -> FastAPI:
    """Create a minimal FastAPI app with just the pool warm router."""
    from api.main import create_app

    app = create_app()
    app.state.pool_client = mock_pool_client
    app.state.vault = _make_mock_vault()
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pool():
    return _MockPoolClient()


@pytest.fixture
def mock_pool_failing():
    return _MockPoolClient(raise_on_hint=True)


@pytest.fixture
async def warm_client(mock_pool):
    app = _make_app(mock_pool)
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client, mock_pool


@pytest.fixture
async def warm_client_failing(mock_pool_failing):
    app = _make_app(mock_pool_failing)
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client, mock_pool_failing


@pytest.fixture
async def unauthed_client(mock_pool):
    app = _make_app(mock_pool)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_warm_happy_path_returns_202(warm_client):
    """POST /api/internal/pool/warm returns 202 with hinted=true and options_hash."""
    client, pool = warm_client
    resp = await client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-2.0"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["hinted"] is True
    assert "options_hash" in data
    assert len(data["options_hash"]) == 16  # SHA-256 truncated to 16 hex chars


async def test_warm_calls_pool_hint(warm_client):
    """POST /api/internal/pool/warm calls pool_client.hint with correct args."""
    client, pool = warm_client
    await client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-2.0"},
    )
    assert len(pool.hint_calls) == 1
    user_id, options_hash, options = pool.hint_calls[0]
    assert user_id == TEST_USER_ID
    assert len(options_hash) == 16


async def test_warm_options_hash_matches_layer_algorithm(warm_client):
    """The returned options_hash must match the layer's _stable_options_hash algorithm.

    Hash includes env (per-user OAuth token) so the warm partition matches the
    acquire-side hash in interactive_agent_layer — subprocesses are consumed.
    """
    from bot.agent_dispatch import _V2_0_OPTIONS

    client, pool = warm_client
    resp = await client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-2.0"},
    )
    assert resp.status_code == 202
    returned_hash = resp.json()["options_hash"]

    # Hash includes env — verify it matches algorithm applied to options+env
    assert len(pool.hint_calls) == 1
    _, hint_hash, hint_options = pool.hint_calls[0]
    expected_hash = _stable_options_hash(hint_options)
    assert returned_hash == expected_hash
    assert hint_hash == expected_hash


async def test_warm_pool_failure_still_returns_202(warm_client_failing):
    """POST /api/internal/pool/warm returns 202 even when the pool client raises."""
    client, pool = warm_client_failing
    resp = await client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-2.0"},
    )
    assert resp.status_code == 202
    data = resp.json()
    # hinted=false when pool call fails — for observability
    assert data["hinted"] is False
    assert "options_hash" in data


async def test_warm_unauthenticated_returns_401(unauthed_client):
    """POST /api/internal/pool/warm returns 401 when no auth cookie."""
    resp = await unauthed_client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-2.0"},
    )
    assert resp.status_code == 401


async def test_warm_unknown_agent_version_returns_400(warm_client):
    """POST /api/internal/pool/warm returns 400 for unknown agent version."""
    client, pool = warm_client
    resp = await client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-99.0"},
    )
    assert resp.status_code == 400
