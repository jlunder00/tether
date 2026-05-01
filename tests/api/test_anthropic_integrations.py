"""API tests for Anthropic OAuth vault endpoints.

TDD: written before handlers existed and confirmed to fail for the right reason.
All tests mock subprocess; no live claude binary required.
These tests do NOT require DATABASE_URL -- they mock the vault and skip DB.
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from tests.api.conftest import TEST_USER_ID, TEST_USERNAME


# ---------------------------------------------------------------------------
# Fixture: lightweight app + authenticated client (no DB needed)
# ---------------------------------------------------------------------------

@pytest.fixture
async def auth_app_client():
    """Authenticated AsyncClient with mock vault; no real DB connection."""
    from api.main import create_app
    from api.auth import create_jwt

    app = create_app()
    # Lifespan does not fire with ASGITransport -- set state directly
    mock_vault = AsyncMock()
    mock_vault.is_connected = AsyncMock(return_value=False)
    mock_vault.store_initial = AsyncMock(return_value=None)
    mock_vault.disconnect = AsyncMock(return_value=None)
    app.state.vault = mock_vault

    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client, mock_vault, app


# ---------------------------------------------------------------------------
# Fixture: clears _pending_setups between tests to prevent state leakage
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_pending_setups():
    """Clear module-level _pending_setups before each test."""
    import api.routes.integrations as ant_routes
    ant_routes._pending_setups.clear()
    yield
    ant_routes._pending_setups.clear()


# ---------------------------------------------------------------------------
# 1. POST /api/integrations/anthropic/start -- returns URL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_returns_url(auth_app_client):
    """Mock _start_pexpect_sync returning a URL; response contains url + expires_in."""
    client, mock_vault, app = auth_app_client

    mock_child = MagicMock()
    expected_url = "https://console.anthropic.com/oauth/authorize?code=abc123"

    with patch(
        "api.routes.integrations._start_pexpect_sync",
        return_value=(mock_child, expected_url),
    ):
        resp = await client.post("/api/integrations/anthropic/start")

    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    # Use startswith to validate exact scheme + netloc — substring 'in' check is
    # insufficient (CodeQL: incomplete URL substring sanitization)
    assert data["url"].startswith("https://console.anthropic.com/"), (
        f"URL must start with exact scheme+netloc, got: {data['url']}"
    )
    assert data["expires_in"] == 600


# ---------------------------------------------------------------------------
# 2. POST /api/integrations/anthropic/start -- 502 when no URL found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_no_url_returns_502(auth_app_client):
    """When _start_pexpect_sync finds no URL, endpoint returns 502."""
    client, mock_vault, app = auth_app_client

    with patch(
        "api.routes.integrations._start_pexpect_sync",
        return_value=(None, None),
    ):
        resp = await client.post("/api/integrations/anthropic/start")

    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# 3. POST /api/integrations/anthropic/complete -- success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_success(auth_app_client):
    """Stash a fake pending entry; complete receives token from _complete_pexpect_sync and persists it."""
    import api.routes.integrations as ant_routes
    client, mock_vault, app = auth_app_client

    fake_token = "sk-ant-oat01-FAKETOKEN_abc123"
    mock_child = MagicMock()

    ant_routes._pending_setups[TEST_USER_ID] = {
        "child": mock_child,
        "started_at": time.time(),
    }

    with patch(
        "api.routes.integrations._complete_pexpect_sync",
        return_value=("ok", fake_token),
    ):
        resp = await client.post(
            "/api/integrations/anthropic/complete",
            json={"code": "auth_code_123"},
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_vault.store_initial.assert_called_once()
    args = mock_vault.store_initial.call_args.args
    assert args[0] == TEST_USER_ID
    assert args[1] == {"oauth_token": fake_token}


@pytest.mark.asyncio
async def test_complete_no_token_in_output_returns_error(auth_app_client):
    """If _complete_pexpect_sync finds no token it returns 'failed'; endpoint surfaces an error."""
    import api.routes.integrations as ant_routes
    client, mock_vault, app = auth_app_client

    mock_child = MagicMock()

    ant_routes._pending_setups[TEST_USER_ID] = {
        "child": mock_child,
        "started_at": time.time(),
    }

    with patch(
        "api.routes.integrations._complete_pexpect_sync",
        return_value=("failed", ""),
    ):
        resp = await client.post(
            "/api/integrations/anthropic/complete",
            json={"code": "auth_code_123"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    mock_vault.store_initial.assert_not_called()


@pytest.mark.asyncio
async def test_complete_success_does_not_log_token(auth_app_client, caplog):
    """The OAuth token must never appear in any log output, even at DEBUG level."""
    import logging
    import api.routes.integrations as ant_routes
    client, mock_vault, app = auth_app_client

    fake_token = "sk-ant-oat01-SECRET_TOKEN_value_xyz789"
    mock_child = MagicMock()
    mock_child.before = (
        b"\x1b[2K\x1b[1Gpasted code\n"
        b"OAuth token created!\n"
        + fake_token.encode()
        + b"\n"
    )

    ant_routes._pending_setups[TEST_USER_ID] = {
        "child": mock_child,
        "started_at": time.time(),
    }

    caplog.set_level(logging.DEBUG, logger="api.routes.integrations")
    with patch(
        "api.routes.integrations._complete_pexpect_sync",
        return_value=("ok", fake_token),
    ):
        resp = await client.post(
            "/api/integrations/anthropic/complete",
            json={"code": "auth_code_123"},
        )
    assert resp.status_code == 200

    for record in caplog.records:
        msg = record.getMessage()
        assert fake_token not in msg, f"token leaked in log record: {record.name} {msg!r}"


# ---------------------------------------------------------------------------
# 4. POST /api/integrations/anthropic/complete -- 404 when no pending setup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_no_pending_returns_404(auth_app_client):
    """No stashed setup for the user -> 404."""
    client, mock_vault, app = auth_app_client
    resp = await client.post(
        "/api/integrations/anthropic/complete",
        json={"code": "some_code"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. POST /api/integrations/anthropic/complete -- 504 on process timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_process_timeout_returns_504(auth_app_client):
    """If _complete_pexpect_sync returns 'timeout', endpoint returns 504."""
    import api.routes.integrations as ant_routes
    client, mock_vault, app = auth_app_client

    mock_child = MagicMock()

    ant_routes._pending_setups[TEST_USER_ID] = {
        "child": mock_child,
        "started_at": time.time(),
    }

    with patch(
        "api.routes.integrations._complete_pexpect_sync",
        return_value=("timeout", ""),
    ):
        resp = await client.post(
            "/api/integrations/anthropic/complete",
            json={"code": "code"},
        )

    assert resp.status_code == 504


# ---------------------------------------------------------------------------
# 6. DELETE /api/integrations/anthropic -- calls vault.disconnect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disconnect_calls_vault(auth_app_client):
    """DELETE endpoint calls vault.disconnect(user_id) and returns {"ok": True}."""
    client, mock_vault, app = auth_app_client

    resp = await client.delete("/api/integrations/anthropic")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_vault.disconnect.assert_called_once_with(TEST_USER_ID)


# ---------------------------------------------------------------------------
# GET /api/integrations/anthropic — connection status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_connected(auth_app_client):
    """GET /integrations/anthropic returns {connected: true} when vault.is_connected is True."""
    client, mock_vault, app = auth_app_client
    mock_vault.is_connected = AsyncMock(return_value=True)

    resp = await client.get("/api/integrations/anthropic")

    assert resp.status_code == 200
    assert resp.json() == {"connected": True}
    mock_vault.is_connected.assert_called_once_with(TEST_USER_ID)


@pytest.mark.asyncio
async def test_status_not_connected(auth_app_client):
    """GET /integrations/anthropic returns {connected: false} when vault.is_connected is False."""
    client, mock_vault, app = auth_app_client
    mock_vault.is_connected = AsyncMock(return_value=False)

    resp = await client.get("/api/integrations/anthropic")

    assert resp.status_code == 200
    assert resp.json() == {"connected": False}


@pytest.mark.asyncio
async def test_status_no_vault_returns_not_connected(auth_app_client):
    """GET /integrations/anthropic returns {connected: false} gracefully when vault is None."""
    client, mock_vault, app = auth_app_client
    app.state.vault = None

    resp = await client.get("/api/integrations/anthropic")

    assert resp.status_code == 200
    assert resp.json() == {"connected": False}


# ---------------------------------------------------------------------------
# 7. POST /api/integrations/anthropic/start -- requires auth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_requires_auth():
    """Unauthenticated request to /start returns 401."""
    from api.main import create_app

    app = create_app()
    app.state.vault = None

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as unauth_client:
        resp = await unauth_client.post("/api/integrations/anthropic/start")

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 8. POST /api/integrations/anthropic/complete -- broken pipe returns 502
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_broken_pipe_returns_502(auth_app_client):
    """If _complete_pexpect_sync returns 'error' (e.g. sendline failed), return 502."""
    import api.routes.integrations as routes
    client, mock_vault, app = auth_app_client

    mock_child = MagicMock()

    routes._pending_setups[TEST_USER_ID] = {
        "child": mock_child,
        "started_at": time.time(),
    }

    with patch(
        "api.routes.integrations._complete_pexpect_sync",
        return_value=("error", ""),
    ):
        resp = await client.post(
            "/api/integrations/anthropic/complete",
            json={"code": "code"},
        )

    assert resp.status_code == 502
    # Entry should be cleaned up
    assert TEST_USER_ID not in routes._pending_setups


# ---------------------------------------------------------------------------
# 9. cfg.VAULT_KEY roundtrip — key format matches what Fernet expects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cfg_vault_key_roundtrip(monkeypatch):
    """A key from Fernet.generate_key().decode() round-trips through cfg → CredentialsVault."""
    from cryptography.fernet import Fernet
    from contextlib import asynccontextmanager

    raw_key = Fernet.generate_key()
    monkeypatch.setenv("TETHER_VAULT_KEY", raw_key.decode())

    from config import loader as config_loader
    config_loader.config._cfg = None

    import importlib
    import api.config as cfg
    importlib.reload(cfg)

    assert cfg.VAULT_KEY is not None

    from api.credentials_vault import CredentialsVault

    vault = CredentialsVault(pool=None, encryption_key=cfg.VAULT_KEY)

    stored: list[bytes] = []

    async def fake_store(conn, user_id, blob):
        stored.append(blob)

    async def fake_get(conn, user_id):
        return stored[-1] if stored else None

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        from unittest.mock import AsyncMock
        yield AsyncMock()

    with patch("api.credentials_vault.store_credentials_blob", side_effect=fake_store), \
         patch("api.credentials_vault.get_credentials_blob", side_effect=fake_get), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):

        await vault.store_initial("user1", {"oauth_token": "sk-ant-oat01-roundtrip"})
        async with vault.materialize("user1") as env:
            assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-roundtrip"}


# ---------------------------------------------------------------------------
# 10. /start pending entry must NOT contain temp_dir
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_pending_entry_has_no_temp_dir(auth_app_client):
    """After /start succeeds, the pending entry must not have a 'temp_dir' key.
    claude setup-token writes only to stdout — no filesystem temp dir needed.
    """
    import api.routes.integrations as ant_routes
    client, mock_vault, app = auth_app_client

    mock_child = MagicMock()
    expected_url = "https://console.anthropic.com/oauth/authorize?code=abc"

    with patch(
        "api.routes.integrations._start_pexpect_sync",
        return_value=(mock_child, expected_url),
    ):
        resp = await client.post("/api/integrations/anthropic/start")

    assert resp.status_code == 200
    entry = ant_routes._pending_setups.get(TEST_USER_ID)
    assert entry is not None
    assert "temp_dir" not in entry, "pending entry must not contain temp_dir after OAuth migration"
