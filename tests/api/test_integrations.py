"""API-layer tests for /api/integrations/google/* routes.

TDD: each test was written before its handler existed and confirmed to fail
for the right reason (404 / ImportError / missing assertion).
"""
from __future__ import annotations

import json
import urllib.parse
from contextlib import asynccontextmanager
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

    # Only patch where the call actually happens — inside the auth provider.
    # The routes module does not call upsert_integration directly on callback.
    with patch(
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


@pytest.mark.asyncio
async def test_disconnect_deletes_synced_tasks(api_client, conn):
    """Disconnect hard-deletes all tasks imported from google_calendar.

    Task C scenario 2: when the user unlinks GCal, all tasks created by
    the sync worker (source='google_calendar') must be removed so stale
    events don't appear in the calendar or plan.
    """
    from db.pg_queries.integrations import upsert_integration

    await upsert_integration(
        conn, TEST_USER_ID, "google_calendar",
        access_token="tok", refresh_token="rt",
    )

    import uuid
    # Insert two tasks that look like they were synced from GCal
    for ext_id in ("gcal-evt-1", "gcal-evt-2"):
        await conn.execute(
            """
            INSERT INTO tasks (uuid, user_id, text, status, source, external_id)
            VALUES ($1, $2::uuid, $3, 'pending', 'google_calendar', $4)
            """,
            uuid.uuid4(), TEST_USER_ID, f"GCal event {ext_id}", ext_id,
        )

    # Verify they exist before disconnect
    rows_before = await conn.fetch(
        "SELECT uuid FROM tasks WHERE user_id = $1::uuid AND source = 'google_calendar'",
        TEST_USER_ID,
    )
    assert len(rows_before) >= 2, "Precondition: synced tasks must exist before disconnect"

    with patch("api.routes.integrations.GoogleCalendarAuth.revoke", new=AsyncMock()):
        resp = await api_client.post("/api/integrations/google/disconnect")

    assert resp.status_code == 200, resp.text

    rows_after = await conn.fetch(
        "SELECT uuid FROM tasks WHERE user_id = $1::uuid AND source = 'google_calendar'",
        TEST_USER_ID,
    )
    assert len(rows_after) == 0, (
        f"All google_calendar tasks must be deleted on disconnect, "
        f"{len(rows_after)} remain"
    )


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

    async def mock_dispatch(pool, integration_id, calendar_id, *, provider, notify_type="poll", **extra):
        dispatched.append({"integration_id": integration_id, "calendar_id": calendar_id,
                           "provider": provider, "notify_type": notify_type})

    monkeypatch.setattr("api.routes.integrations.dispatch_sync", mock_dispatch)

    resp = await api_client.post("/api/integrations/google/sync")
    assert resp.status_code == 200

    calendar_ids = {d["calendar_id"] for d in dispatched}
    assert "primary" in calendar_ids
    assert "cal2@group.calendar.google.com" in calendar_ids
    assert all(d["provider"] == "google_calendar" for d in dispatched)
    assert all(d["notify_type"] == "poll" for d in dispatched)


@pytest.mark.asyncio
async def test_sync_no_integration_returns_404(api_client):
    """Manual sync when no integration is connected returns 404."""
    resp = await api_client.post("/api/integrations/google/sync")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. POST /api/integrations/google/webhook — inline BackgroundTask (Phase F)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_returns_200_immediately(api_client, monkeypatch):
    """Webhook endpoint returns 200 immediately; dispatches BackgroundTask."""
    called: list[tuple] = []

    async def mock_process(channel_id, resource_state, pool):
        called.append((channel_id, resource_state))

    monkeypatch.setattr("api.routes.integrations._process_gcal_event", mock_process)

    resp = await api_client.post(
        "/api/integrations/google/webhook",
        headers={
            "X-Goog-Channel-Id": "ch_test_001",
            "X-Goog-Resource-Id": "res_001",
            "X-Goog-Resource-State": "exists",
        },
    )
    assert resp.status_code == 200
    assert ("ch_test_001", "exists") in called


@pytest.mark.asyncio
async def test_webhook_dispatches_background_task_args(api_client, monkeypatch):
    """Webhook handler passes channel_id and resource_state to _process_gcal_event."""
    captured: list[dict] = []

    async def mock_process(channel_id, resource_state, pool):
        captured.append({"channel_id": channel_id, "resource_state": resource_state})

    monkeypatch.setattr("api.routes.integrations._process_gcal_event", mock_process)

    resp = await api_client.post(
        "/api/integrations/google/webhook",
        headers={
            "X-Goog-Channel-Id": "my-channel-123",
            "X-Goog-Resource-State": "exists",
        },
    )
    assert resp.status_code == 200
    assert len(captured) == 1
    assert captured[0]["channel_id"] == "my-channel-123"
    assert captured[0]["resource_state"] == "exists"


@pytest.mark.asyncio
async def test_webhook_dispatch_does_not_call_dispatch_sync(api_client, monkeypatch):
    """Webhook handler no longer calls dispatch_sync (removed PG NOTIFY from path)."""
    dispatch_called = []

    async def spy_dispatch(*args, **kwargs):
        dispatch_called.append(1)

    async def mock_process(channel_id, resource_state, pool):
        pass

    monkeypatch.setattr("api.routes.integrations.dispatch_sync", spy_dispatch)
    monkeypatch.setattr("api.routes.integrations._process_gcal_event", mock_process)

    resp = await api_client.post(
        "/api/integrations/google/webhook",
        headers={
            "X-Goog-Channel-Id": "ch_001",
            "X-Goog-Resource-State": "exists",
        },
    )
    assert resp.status_code == 200
    assert dispatch_called == [], "dispatch_sync must not be called from the webhook handler"


@pytest.mark.asyncio
async def test_webhook_unknown_channel_still_200(api_client):
    """Webhook with unknown channel-id still returns 200 (Google's requirement).

    _process_gcal_event finds no integration_sync_state row and returns silently.
    """
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
# 5b. _process_gcal_event unit tests (Phase F inline handler)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_gcal_event_skips_sync_resource_state(monkeypatch):
    """_process_gcal_event returns early for resource_state='sync' (channel registration ping)."""
    from api.routes import integrations as routes

    handle_called = []

    async def mock_handle_webhook(self, integration_id, payload):
        handle_called.append(1)

    monkeypatch.setattr(
        "api.routes.integrations.GoogleCalendarSync.handle_webhook",
        mock_handle_webhook,
    )

    # Should return without calling handle_webhook
    await routes._process_gcal_event("ch_001", "sync", pool=None)
    assert handle_called == []


@pytest.mark.asyncio
async def test_process_gcal_event_skips_none_channel_id(monkeypatch):
    """_process_gcal_event returns early when channel_id is None."""
    from api.routes import integrations as routes

    handle_called = []

    async def mock_handle_webhook(self, integration_id, payload):
        handle_called.append(1)

    monkeypatch.setattr(
        "api.routes.integrations.GoogleCalendarSync.handle_webhook",
        mock_handle_webhook,
    )

    await routes._process_gcal_event(None, "exists", pool=None)
    assert handle_called == []


@pytest.mark.asyncio
async def test_process_gcal_event_unknown_channel_no_raise(monkeypatch):
    """_process_gcal_event logs and returns silently when channel has no sync state row."""
    from api.routes import integrations as routes
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        yield conn

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)

    # Must not raise
    await routes._process_gcal_event("ch-unknown", "exists", pool=None)


@pytest.mark.asyncio
async def test_process_gcal_event_calls_handle_webhook(monkeypatch):
    """_process_gcal_event resolves integration_id from channel_id and calls handle_webhook."""
    import uuid
    from api.routes import integrations as routes
    from contextlib import asynccontextmanager

    fake_integration_id = str(uuid.uuid4())

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"integration_id": uuid.UUID(fake_integration_id)})
        yield conn

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)

    handle_calls: list[dict] = []

    async def mock_handle_webhook(self, integration_id, payload):
        handle_calls.append({"integration_id": integration_id, "channel_id": payload.channel_id})

    monkeypatch.setattr(
        "api.routes.integrations.GoogleCalendarSync.handle_webhook",
        mock_handle_webhook,
    )

    await routes._process_gcal_event("ch-known", "exists", pool=None)

    assert len(handle_calls) == 1
    assert handle_calls[0]["integration_id"] == fake_integration_id
    assert handle_calls[0]["channel_id"] == "ch-known"


@pytest.mark.asyncio
async def test_process_gcal_event_exception_does_not_propagate(monkeypatch):
    """_process_gcal_event catches and logs exceptions from handle_webhook."""
    import uuid
    from api.routes import integrations as routes
    from contextlib import asynccontextmanager

    fake_id = str(uuid.uuid4())

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"integration_id": uuid.UUID(fake_id)})
        yield conn

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)

    async def mock_handle_webhook_raises(self, integration_id, payload):
        raise RuntimeError("Google API flaked")

    monkeypatch.setattr(
        "api.routes.integrations.GoogleCalendarSync.handle_webhook",
        mock_handle_webhook_raises,
    )

    # Must not propagate the exception
    await routes._process_gcal_event("ch-boom", "exists", pool=None)


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
async def test_calendars_list_google_401_returns_401(api_client, conn):
    """GET /calendars returns 401 when Google says the token is expired."""
    from db.pg_queries.integrations import upsert_integration

    await upsert_integration(conn, TEST_USER_ID, "google_calendar", access_token="expired_tok")

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.is_success = False

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("api.routes.integrations.httpx.AsyncClient", return_value=mock_client):
        resp = await api_client.get("/api/integrations/google/calendars")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_calendars_list_google_502_on_error(api_client, conn):
    """GET /calendars returns 502 when Google returns a non-401 error."""
    from db.pg_queries.integrations import upsert_integration

    await upsert_integration(conn, TEST_USER_ID, "google_calendar", access_token="tok")

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.is_success = False

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("api.routes.integrations.httpx.AsyncClient", return_value=mock_client):
        resp = await api_client.get("/api/integrations/google/calendars")

    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_calendars_list_no_integration_returns_404(api_client):
    """GET /calendars when not connected returns 404."""
    resp = await api_client.get("/api/integrations/google/calendars")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_calendars_list_google_401_returns_401(api_client, conn):
    """GET /calendars returns 401 when Google says the token is expired."""
    from db.pg_queries.integrations import upsert_integration

    await upsert_integration(conn, TEST_USER_ID, "google_calendar", access_token="expired_tok")

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.is_success = False

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("api.routes.integrations.httpx.AsyncClient", return_value=mock_client):
        resp = await api_client.get("/api/integrations/google/calendars")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_calendars_list_google_502_on_error(api_client, conn):
    """GET /calendars returns 502 when Google returns a non-401 error."""
    from db.pg_queries.integrations import upsert_integration

    await upsert_integration(conn, TEST_USER_ID, "google_calendar", access_token="tok")

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.is_success = False

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("api.routes.integrations.httpx.AsyncClient", return_value=mock_client):
        resp = await api_client.get("/api/integrations/google/calendars")

    assert resp.status_code == 502


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


# ---------------------------------------------------------------------------
# 8. Callback fires initial sync + webhook registration as background task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_schedules_initial_sync_background_task(api_client, monkeypatch):
    """After successful callback, the helper that runs initial sync +
    webhook registration is dispatched as a FastAPI BackgroundTask."""
    state = _make_state(TEST_USER_ID)

    # Stub the OAuth token exchange so the callback succeeds without HTTP.
    async def fake_handle_callback(self, user_id, code):
        return None
    monkeypatch.setattr(
        "api.routes.integrations.GoogleCalendarAuth.handle_callback",
        fake_handle_callback,
    )

    called: dict = {}

    async def fake_helper(pool, user_id):
        called["pool"] = pool
        called["user_id"] = user_id

    monkeypatch.setattr(
        "api.routes.integrations._initial_sync_and_register",
        fake_helper,
    )

    resp = await api_client.get(
        f"/api/integrations/google/callback?code=auth_code&state={state}",
        follow_redirects=False,
    )

    assert resp.status_code in (302, 307)
    # Background task must have been dispatched with the user_id from state.
    assert called.get("user_id") == TEST_USER_ID
    assert called.get("pool") is not None


@pytest.mark.asyncio
async def test_initial_sync_dispatches_for_each_selected_calendar(monkeypatch):
    """_initial_sync_and_register dispatches a poll sync per selected calendar
    and registers a webhook per selected calendar."""
    from api.routes import integrations as routes

    fake_row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "metadata": {"selected_calendar_ids": ["primary", "cal2@group.calendar.google.com"]},
    }

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield None

    async def fake_get_integration(conn, user_id, provider):
        return fake_row

    dispatched: list[dict] = []

    async def fake_dispatch(pool, integration_id, calendar_id, *, provider, notify_type="poll", **extra):
        dispatched.append({
            "integration_id": integration_id,
            "calendar_id": calendar_id,
            "provider": provider,
            "notify_type": notify_type,
        })

    registered: list[tuple] = []

    async def fake_register(self, integration_id, calendar_id):
        registered.append((integration_id, calendar_id))

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)
    monkeypatch.setattr("api.routes.integrations.get_integration", fake_get_integration)
    monkeypatch.setattr("api.routes.integrations.dispatch_sync", fake_dispatch)
    monkeypatch.setattr(
        "api.routes.integrations.GoogleCalendarSync.register_webhook",
        fake_register,
    )

    await routes._initial_sync_and_register(pool=None, user_id=TEST_USER_ID)

    cal_ids = {d["calendar_id"] for d in dispatched}
    assert cal_ids == {"primary", "cal2@group.calendar.google.com"}
    assert all(d["provider"] == "google_calendar" for d in dispatched)
    assert all(d["notify_type"] == "poll" for d in dispatched)
    reg_ids = {r[1] for r in registered}
    assert reg_ids == {"primary", "cal2@group.calendar.google.com"}


@pytest.mark.asyncio
async def test_initial_sync_tolerates_webhook_failure(monkeypatch):
    """register_webhook is best-effort: dispatch still happens and the
    helper does not raise even if webhook registration blows up."""
    from api.routes import integrations as routes

    fake_row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "metadata": {"selected_calendar_ids": ["primary"]},
    }

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield None

    async def fake_get_integration(conn, user_id, provider):
        return fake_row

    dispatched: list[str] = []

    async def fake_dispatch(pool, integration_id, calendar_id, *, provider, notify_type="poll", **extra):
        dispatched.append(calendar_id)

    async def fake_register_fail(self, integration_id, calendar_id):
        raise RuntimeError("tunnel down")

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)
    monkeypatch.setattr("api.routes.integrations.get_integration", fake_get_integration)
    monkeypatch.setattr("api.routes.integrations.dispatch_sync", fake_dispatch)
    monkeypatch.setattr(
        "api.routes.integrations.GoogleCalendarSync.register_webhook",
        fake_register_fail,
    )

    # Must not raise.
    await routes._initial_sync_and_register(pool=None, user_id=TEST_USER_ID)
    assert dispatched == ["primary"]


@pytest.mark.asyncio
async def test_initial_sync_no_integration_returns_silently(monkeypatch):
    """If the integration row is missing, helper logs and returns without
    dispatching or raising."""
    from api.routes import integrations as routes

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield None

    async def fake_get_integration(conn, user_id, provider):
        return None

    dispatched: list = []

    async def fake_dispatch(*args, **kwargs):
        dispatched.append(1)

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)
    monkeypatch.setattr("api.routes.integrations.get_integration", fake_get_integration)
    monkeypatch.setattr("api.routes.integrations.dispatch_sync", fake_dispatch)

    await routes._initial_sync_and_register(pool=None, user_id=TEST_USER_ID)
    assert dispatched == []


@pytest.mark.asyncio
async def test_initial_sync_defaults_to_primary_when_no_metadata(monkeypatch):
    """If the integration has no selected_calendar_ids, defaults to ['primary']."""
    from api.routes import integrations as routes

    fake_row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "metadata": None,
    }

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield None

    async def fake_get_integration(conn, user_id, provider):
        return fake_row

    dispatched: list[str] = []

    async def fake_dispatch(pool, integration_id, calendar_id, *, provider, notify_type="poll", **extra):
        dispatched.append(calendar_id)

    async def fake_register(self, integration_id, calendar_id):
        pass

    monkeypatch.setattr("db.postgres.get_conn", fake_get_conn)
    monkeypatch.setattr("api.routes.integrations.get_integration", fake_get_integration)
    monkeypatch.setattr("api.routes.integrations.dispatch_sync", fake_dispatch)
    monkeypatch.setattr(
        "api.routes.integrations.GoogleCalendarSync.register_webhook",
        fake_register,
    )

    await routes._initial_sync_and_register(pool=None, user_id=TEST_USER_ID)
    assert dispatched == ["primary"]
