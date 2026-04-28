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
    """Mock subprocess that outputs a URL on stdout; response contains url + expires_in."""
    client, mock_vault, app = auth_app_client

    url_line = b"Visit https://console.anthropic.com/oauth/authorize?code=abc123 to authorize\n"

    mock_proc = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()
    mock_proc.stdout.read = AsyncMock(return_value=url_line)
    mock_proc.stderr.read = AsyncMock(return_value=b"")
    mock_proc.pid = 12345
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=None)

    with patch(
        "api.routes.integrations.asyncio.create_subprocess_exec",
        return_value=mock_proc,
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
    """When subprocess returns no URL, endpoint returns 502."""
    client, mock_vault, app = auth_app_client

    mock_proc = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stderr = AsyncMock()
    mock_proc.stdout.read = AsyncMock(return_value=b"some garbage output no url here\n")
    mock_proc.stderr.read = AsyncMock(return_value=b"error: something went wrong\n")
    mock_proc.pid = 12346
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=None)

    with patch(
        "api.routes.integrations.asyncio.create_subprocess_exec",
        return_value=mock_proc,
    ):
        resp = await client.post("/api/integrations/anthropic/start")

    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# 3. POST /api/integrations/anthropic/complete -- success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_success(auth_app_client, tmp_path):
    """Stash a fake pending entry; complete succeeds and calls vault.store_initial."""
    import api.routes.integrations as ant_routes
    client, mock_vault, app = auth_app_client

    # Create a fake credentials.json in a temp dir
    creds_data = {"api_key": "sk-ant-test", "type": "oauth"}
    creds_file = tmp_path / ".credentials.json"
    creds_file.write_text(json.dumps(creds_data))

    mock_proc = AsyncMock()
    mock_proc.stdin = AsyncMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.returncode = 0

    # Stash fake pending entry for TEST_USER_ID
    ant_routes._pending_setups[TEST_USER_ID] = {
        "proc": mock_proc,
        "temp_dir": str(tmp_path),
        "started_at": time.time(),
    }

    resp = await client.post(
        "/api/integrations/anthropic/complete",
        json={"code": "auth_code_123"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    mock_vault.store_initial.assert_called_once()
    call_args = mock_vault.store_initial.call_args
    assert call_args[0][0] == TEST_USER_ID  # first positional arg is user_id


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
async def test_complete_process_timeout_returns_504(auth_app_client, tmp_path):
    """If asyncio.wait_for times out on proc.wait(), endpoint returns 504."""
    import api.routes.integrations as ant_routes
    client, mock_vault, app = auth_app_client

    mock_proc = AsyncMock()
    mock_proc.stdin = AsyncMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    # wait() returns 0 immediately; asyncio.wait_for is patched below to raise TimeoutError
    # so the direct await proc.wait() after kill() won't hang
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.kill = MagicMock()

    ant_routes._pending_setups[TEST_USER_ID] = {
        "proc": mock_proc,
        "temp_dir": str(tmp_path),
        "started_at": time.time(),
    }

    # wait_for is called twice: once for stdin.drain (should succeed → None),
    # once for proc.wait (should timeout). Use a side_effect list.
    mock_wait_for = AsyncMock(side_effect=[None, asyncio.TimeoutError()])
    with patch("api.routes.integrations.asyncio.wait_for", mock_wait_for):
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
async def test_complete_broken_pipe_returns_502(auth_app_client, tmp_path):
    """If stdin.drain raises BrokenPipeError (process already exited), return 502."""
    import api.routes.integrations as routes
    client, mock_vault, app = auth_app_client

    mock_proc = AsyncMock()
    mock_proc.stdin = AsyncMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = AsyncMock(side_effect=BrokenPipeError("pipe broken"))
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=None)

    routes._pending_setups[TEST_USER_ID] = {
        "proc": mock_proc,
        "temp_dir": str(tmp_path),
        "started_at": time.time(),
    }

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
async def test_cfg_vault_key_roundtrip(tmp_path, monkeypatch):
    """A key from Fernet.generate_key().decode() round-trips through cfg → CredentialsVault."""
    from cryptography.fernet import Fernet
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    raw_key = Fernet.generate_key()           # bytes: URL-safe base64, 44 chars
    key_str = raw_key.decode()                # str: what operator puts in TETHER_VAULT_KEY

    monkeypatch.setenv("TETHER_VAULT_KEY", key_str)

    # Reset the config singleton's cache so it re-resolves placeholders from env,
    # then reload api.config so VAULT_KEY is recomputed with the new value.
    from config import loader as config_loader
    config_loader.config._cfg = None

    import importlib
    import api.config as cfg
    importlib.reload(cfg)

    assert cfg.VAULT_KEY is not None, "VAULT_KEY should be set"

    from api.credentials_vault import CredentialsVault

    vault = CredentialsVault(pool=None, encryption_key=cfg.VAULT_KEY, creds_dir=tmp_path)

    original = {"token": "test-roundtrip"}
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

        await vault.store_initial("user1", original)
        async with vault.materialize("user1") as creds_dir:
            import json
            loaded = json.loads((creds_dir / ".credentials.json").read_text())

    assert loaded == original
