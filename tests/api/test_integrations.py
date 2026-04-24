"""API-layer tests for /api/integrations/google/* routes.

TDD: each test was written before its handler existed and confirmed to fail
for the right reason (404 / ImportError / missing assertion).
"""
from __future__ import annotations

import json
import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from tests.api.conftest import TEST_USER_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(user_id: str) -> str:
    """Generate a valid OAuth state token using the same helper as the route."""
    from integrations.google_calendar.auth import make_oauth_state
    return make_oauth_state(user_id)


def _parse_redirect_params(location: str) -> dict:
    """Extract query params from a redirect Location header."""
    parsed = urllib.parse.urlparse(location)
    return dict(urllib.parse.parse_qsl(parsed.query))


# ---------------------------------------------------------------------------
# 1. GET /api/integrations/google/connect — redirect to Google OAuth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_redirects_to_google(api_client, monkeypatch):
    """Connect endpoint redirects to Google with correct OAuth params."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    # Reload config so env var is picked up
    import api.config as cfg
    import importlib
    importlib.reload(cfg)

    resp = await api_client.get(
        "/api/integrations/google/connect",
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert "accounts.google.com/o/oauth2/v2/auth" in location

    params = _parse_redirect_params(location)
    assert params["access_type"] == "offline"
    assert params["prompt"] == "consent"
    assert "calendar.readonly" in params["scope"]
    assert "state" in params
    assert params["response_type"] == "code"


@pytest.mark.asyncio
async def test_connect_requires_auth(api_client, monkeypatch):
    """Unauthenticated request to connect returns 401."""
    from httpx import AsyncClient, ASGITransport
    from api.main import create_app
    from db.pool_middleware import get_db_conn

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")

    # Build an unauthenticated client
    async def override():
        # Reuse pool from api_client's pool — not needed here, just skip
        yield

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as unauth_client:
        resp = await unauth_client.get(
            "/api/integrations/google/connect",
            follow_redirects=False,
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2. GET /api/integrations/google/callback — exchange code, store tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_stores_tokens(api_client, monkeypatch):
    """Callback exchanges code for tokens and upserts user_integrations."""
    import api.config as cfg
    import importlib
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    importlib.reload(cfg)

    state = _make_state(TEST_USER_ID)

    # Track what upsert_integration is called with
    upserted: dict = {}

    async def mock_upsert(conn, user_id, provider, **kwargs):
        upserted.update({"user_id": user_id, "provider": provider, **kwargs})
        return {
            "id": "aaaaaaaa-0000-0000-0000-000000000001",
            "user_id": user_id,
            "provider": provider,
            **kwargs,
        }

    # Patch at the routes level (where it's imported)
    with patch(
        "api.routes.integrations.upsert_integration",
        side_effect=mock_upsert,
    ), patch(
        "integrations.google_calendar.auth.upsert_integration",
        side_effect=mock_upsert,
    ):
        # Mock the Google token exchange
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "ya29.mock_access_token",
            "refresh_token": "1//mock_refresh_token",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/calendar.readonly",
            "token_type": "Bearer",
        }

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            resp = await api_client.get(
                f"/api/integrations/google/callback?code=auth_code&state={state}",
                follow_redirects=False,
            )

    assert resp.status_code in (302, 307)
    assert upserted.get("user_id") == TEST_USER_ID
    assert upserted.get("provider") == "google_calendar"
    assert upserted.get("access_token") == "ya29.mock_access_token"
    assert upserted.get("refresh_token") == "1//mock_refresh_token"


@pytest.mark.asyncio
async def test_callback_rejects_invalid_state(api_client):
    """Callback with a tampered state returns 400."""
    resp = await api_client.get(
        "/api/integrations/google/callback?code=auth_code&state=InvalidBase64!!",
        follow_redirects=False,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 3. POST /api/integrations/google/disconnect — revoke + delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disconnect_deletes_integration(api_client, conn):
    """Disconnect removes the integration row."""
    from db.pg_queries.integrations import upsert_integration, get_integration

    # Insert a row via the test conn (rolled-back after test)
    await upsert_integration(
        conn, TEST_USER_ID, "google_calendar",
        access_token="tok", refresh_token="rt",
    )
    row = await get_integration(conn, TEST_USER_ID, "google_calendar")
    assert row is not None

    # Patch revoke to be a no-op (avoids real HTTP + pool usage)
    with patch("api.routes.integrations.GoogleCalendarAuth.revoke", new=AsyncMock()):
        resp = await api_client.post("/api/integrations/google/disconnect")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    remaining = await get_integration(conn, TEST_USER_ID, "google_calendar")
    assert remaining is None


@pytest.mark.asyncio
async def test_disconnect_no_integration_returns_ok(api_client):
    """Disconnect when no integration exists returns 200 gracefully."""
    with patch("api.routes.integrations.GoogleCalendarAuth.revoke", new=AsyncMock()):
        resp = await api_client.post("/api/integrations/google/disconnect")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 4. POST /api/integrations/google/sync — manual sync via PG NOTIFY
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_dispatches_notify(api_client, conn, monkeypatch):
    """Manual sync trigger calls dispatch_sync for each selected calendar."""
    from db.pg_queries.integrations import upsert_integration

    await upsert_integration(
        conn, TEST_USER_ID, "google_calendar",
        access_token="tok",
        metadata={"selected_calendar_ids": ["primary", "cal2@group.calendar.google.com"]},
    )
    row = await conn.fetchrow(
        "SELECT id FROM user_integrations WHERE user_id = $1 AND provider = $2",
        TEST_USER_ID, "google_calendar",
    )
    integration_id = str(row["id"])

    dispatched: list[dict] = []

    async def mock_dispatch(conn, integration_id, calendar_id):
        dispatched.append({"integration_id": integration_id, "calendar_id": calendar_id})

    monkeypatch.setattr("api.routes.integrations.dispatch_sync", mock_dispatch)

    resp = await api_client.post("/api/integrations/google/sync")
    assert resp.status_code == 200

    calendar_ids = {d["calendar_id"] for d in dispatched}
    assert "primary" in calendar_ids
    assert "cal2@group.calendar.google.com" in calendar_ids


@pytest.mark.asyncio
async def test_sync_no_integration_returns_404(api_client):
    """Manual sync when no integration is connected returns 404."""
    resp = await api_client.post("/api/integrations/google/sync")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. POST /api/integrations/google/webhook — must return 200 fast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_returns_200_immediately(api_client, monkeypatch):
    """Webhook endpoint returns 200 immediately regardless of payload."""
    # Monkeypatch dispatch_sync to be a no-op
    async def mock_dispatch(conn, integration_id, calendar_id):
        pass
    monkeypatch.setattr("api.routes.integrations.dispatch_sync", mock_dispatch)

    resp = await api_client.post(
        "/api/integrations/google/webhook",
        headers={
            "X-Goog-Channel-Id": "ch_test_001",
            "X-Goog-Resource-Id": "res_001",
            "X-Goog-Resource-State": "exists",
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_unknown_channel_still_200(api_client):
    """Webhook with unknown channel-id still returns 200 (Google's requirement)."""
    resp = await api_client.post(
        "/api/integrations/google/webhook",
        headers={
            "X-Goog-Channel-Id": "unknown-channel",
            "X-Goog-Resource-Id": "res_001",
            "X-Goog-Resource-State": "exists",
        },
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 6. GET /api/integrations/google/calendars — list user's Google calendars
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendars_list_returns_google_calendar_items(api_client, conn, monkeypatch):
    """GET /calendars calls Google API and returns list of calendars."""
    from db.pg_queries.integrations import upsert_integration

    await upsert_integration(
        conn, TEST_USER_ID, "google_calendar",
        access_token="tok",
        metadata={"selected_calendar_ids": ["primary"]},
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "items": [
            {"id": "primary", "summary": "My Calendar", "primary": True},
            {"id": "work@group.calendar.google.com", "summary": "Work"},
        ]
    }

    # Patch the AsyncClient constructor in the routes module, not the class
    # method globally — the global patch intercepts the test client's own GET.
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("api.routes.integrations.httpx.AsyncClient", return_value=mock_client):
        resp = await api_client.get("/api/integrations/google/calendars")

    assert resp.status_code == 200
    data = resp.json()
    assert "calendars" in data
    assert any(c["id"] == "primary" for c in data["calendars"])
    assert any(c["id"] == "work@group.calendar.google.com" for c in data["calendars"])


@pytest.mark.asyncio
async def test_calendars_list_no_integration_returns_404(api_client):
    """GET /calendars when not connected returns 404."""
    resp = await api_client.get("/api/integrations/google/calendars")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 7. PATCH /api/integrations/google/calendars — update selected calendar IDs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendars_patch_updates_metadata(api_client, conn, monkeypatch):
    """PATCH /calendars updates selected_calendar_ids in metadata."""
    from db.pg_queries.integrations import upsert_integration, get_integration

    await upsert_integration(
        conn, TEST_USER_ID, "google_calendar",
        access_token="tok",
        metadata={"selected_calendar_ids": ["primary"]},
    )

    new_ids = ["primary", "work@group.calendar.google.com"]
    resp = await api_client.patch(
        "/api/integrations/google/calendars",
        json={"calendar_ids": new_ids},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["selected_calendar_ids"]) == set(new_ids)

    # Verify persisted
    updated = await get_integration(conn, TEST_USER_ID, "google_calendar")
    assert set(updated["metadata"]["selected_calendar_ids"]) == set(new_ids)


@pytest.mark.asyncio
async def test_calendars_patch_no_integration_returns_404(api_client):
    """PATCH /calendars when not connected returns 404."""
    resp = await api_client.patch(
        "/api/integrations/google/calendars",
        json={"calendar_ids": ["primary"]},
    )
    assert resp.status_code == 404
