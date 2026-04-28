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
    import api.routes.anthropic_integrations as ant_routes
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
        "api.routes.anthropic_integrations.asyncio.create_subprocess_exec",
        return_value=mock_proc,
    ):
        resp = await client.post("/api/integrations/anthropic/start")

    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert "console.anthropic.com" in data["url"]
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
        "api.routes.anthropic_integrations.asyncio.create_subprocess_exec",
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
    import api.routes.anthropic_integrations as ant_routes
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
    import api.routes.anthropic_integrations as ant_routes
    client, mock_vault, app = auth_app_client

    mock_proc = AsyncMock()
    mock_proc.stdin = AsyncMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = AsyncMock()

    async def never_returns():
        await asyncio.sleep(9999)

    mock_proc.wait = never_returns
    mock_proc.kill = MagicMock()

    ant_routes._pending_setups[TEST_USER_ID] = {
        "proc": mock_proc,
        "temp_dir": str(tmp_path),
        "started_at": time.time(),
    }

    with patch("api.routes.anthropic_integrations.asyncio.wait_for", side_effect=asyncio.TimeoutError):
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
