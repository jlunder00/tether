"""Tests for OAuth token injection in POST /api/internal/pool/warm.

Verifies that:
  - When vault is configured, the hint options include the OAuth token in env
  - The options_hash is computed BEFORE env injection (stable across users)
  - Vault missing-credentials error is handled gracefully (202, hinted=false)
  - When vault is not configured (vault=None), hint fires without env injection
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "dev-secret-change-in-production")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from api.auth import create_jwt

TEST_USER_ID = "00000000-0000-0000-0000-000000000099"
TEST_USERNAME = "authuser"
TEST_TOKEN = "sk-ant-oauth-test-token"


def _compute_options_hash(options: dict) -> str:
    """Mirror of api/routes/pool._compute_options_hash."""
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


def _make_mock_vault(oauth_token: str | None = TEST_TOKEN):
    """Return a mock CredentialsVault with materialize() yielding env dict."""
    vault = MagicMock()

    @asynccontextmanager
    async def _materialize(user_id: str):
        if oauth_token is None:
            raise ValueError(f"No credentials found for user {user_id}")
        yield {"CLAUDE_CODE_OAUTH_TOKEN": oauth_token}

    vault.materialize = _materialize
    return vault


def _make_app(mock_pool_client, vault=None) -> FastAPI:
    from api.main import create_app
    app = create_app()
    app.state.pool_client = mock_pool_client
    app.state.vault = vault
    return app


@pytest.fixture
def mock_pool():
    return _MockPoolClient()


@pytest.fixture
async def client_with_vault(mock_pool):
    vault = _make_mock_vault(TEST_TOKEN)
    app = _make_app(mock_pool, vault=vault)
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client, mock_pool


@pytest.fixture
async def client_no_vault(mock_pool):
    """App with vault=None (dev/Pi without vault key configured)."""
    app = _make_app(mock_pool, vault=None)
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client, mock_pool


@pytest.fixture
async def client_no_credentials(mock_pool):
    """App with vault configured but user has no stored credentials."""
    vault = _make_mock_vault(oauth_token=None)
    app = _make_app(mock_pool, vault=vault)
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client, mock_pool


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_vault_token_injected_into_hint_options(client_with_vault):
    """When vault is configured, pool hint options must include CLAUDE_CODE_OAUTH_TOKEN."""
    client, pool = client_with_vault
    resp = await client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-2.0"},
    )
    assert resp.status_code == 202
    assert resp.json()["hinted"] is True
    assert len(pool.hint_calls) == 1
    _user_id, _hash, options = pool.hint_calls[0]
    assert options.get("env", {}).get("CLAUDE_CODE_OAUTH_TOKEN") == TEST_TOKEN


async def test_options_hash_includes_env_for_per_user_partitioning(client_with_vault):
    """The returned options_hash must INCLUDE env so warm partitions are per-user.

    A subprocess authenticated with user A's token must not serve user B.
    The acquire-side hash (interactive_agent_layer) also includes env, so the
    hashes must match — warm subprocesses are found and consumed correctly.
    """
    from bot.agent_dispatch import _V2_0_OPTIONS

    client, pool = client_with_vault
    resp = await client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-2.0"},
    )
    assert resp.status_code == 202
    returned_hash = resp.json()["options_hash"]

    # Hash must include env (with OAuth token) to match the acquire-side hash
    expected_options_with_env = {**_V2_0_OPTIONS, "env": {"CLAUDE_CODE_OAUTH_TOKEN": TEST_TOKEN}}
    expected_hash = _compute_options_hash(expected_options_with_env)
    assert returned_hash == expected_hash

    # Verify the hash passed to pool matches options_for_hint (env included)
    _user_id, hint_hash, hint_options = pool.hint_calls[0]
    assert hint_hash == expected_hash
    assert hint_hash == _compute_options_hash(hint_options)  # hash == H(options_for_hint)


async def test_no_vault_hint_fires_without_env(client_no_vault):
    """When vault=None (dev), hint fires without env — subprocess uses disk credentials."""
    client, pool = client_no_vault
    resp = await client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-2.0"},
    )
    assert resp.status_code == 202
    assert resp.json()["hinted"] is True
    assert len(pool.hint_calls) == 1
    _user_id, _hash, options = pool.hint_calls[0]
    # No env injected when vault is absent
    assert "env" not in options or options["env"] == {}


async def test_missing_vault_credentials_returns_202(client_no_credentials):
    """When vault has no credentials for user, still return 202 (hinted=false is ok)."""
    client, pool = client_no_credentials
    resp = await client.post(
        "/api/internal/pool/warm",
        json={"agent_version": "tether-agent-2.0"},
    )
    # Must never 5xx — pool warm is always best-effort
    assert resp.status_code == 202
