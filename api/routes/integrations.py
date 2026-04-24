"""Google Calendar integration routes.

Endpoints (all under /api/integrations/google/):
  GET  /connect      — initiate OAuth, redirect to Google consent
  GET  /callback     — exchange code, store tokens (unauthenticated — comes from Google)
  POST /disconnect   — revoke tokens + delete integration
  POST /sync         — manual sync trigger via PG NOTIFY
  POST /webhook      — receive Google push notifications (must return 200 fast)
  GET  /calendars    — list user's calendars from Google API
  PATCH /calendars   — update selected calendar IDs in metadata
"""
from __future__ import annotations

import logging

import asyncpg
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

import api.config as cfg
from api.auth import auth_dependency
from db.pg_queries.integrations import (
    delete_integration,
    get_integration,
    upsert_integration,
)
from db.pool_middleware import get_db_conn
from integrations.google_calendar.auth import (
    GoogleCalendarAuth,
    verify_oauth_state,
)
from sync.dispatch import dispatch_sync  # re-exported so tests can monkeypatch at this name

logger = logging.getLogger(__name__)
router = APIRouter()

_PROVIDER = "google_calendar"
_GCAL_CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CalendarPatchBody(BaseModel):
    calendar_ids: list[str]


# ---------------------------------------------------------------------------
# 1. GET /integrations/google/connect
# ---------------------------------------------------------------------------

@router.get("/integrations/google/connect")
async def google_connect(
    request: Request,
    _auth: dict = Depends(auth_dependency),
):
    """Redirect authenticated user to Google's OAuth consent screen."""
    if not cfg.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=404, detail="Google integration not configured")

    user_id = request.state.user_id
    provider = GoogleCalendarAuth(request.app.state.pool)
    url = await provider.get_auth_url(user_id)
    return RedirectResponse(url)


# ---------------------------------------------------------------------------
# 2. GET /integrations/google/callback (unauthenticated — Google redirects here)
# ---------------------------------------------------------------------------

@router.get("/integrations/google/callback")
async def google_callback(
    request: Request,
    code: str,
    state: str,
):
    """Exchange authorization code for tokens and persist them.

    User identity is recovered from the signed `state` parameter — no cookie
    is reliably available on this cross-site redirect.
    """
    try:
        user_id = verify_oauth_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        provider = GoogleCalendarAuth(request.app.state.pool)
        await provider.handle_callback(user_id, code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Google Calendar callback failed for user %s", user_id)
        raise HTTPException(status_code=502, detail="Token exchange failed")

    return RedirectResponse("/plan/day")


# ---------------------------------------------------------------------------
# 3. POST /integrations/google/disconnect
# ---------------------------------------------------------------------------

@router.post("/integrations/google/disconnect")
async def google_disconnect(
    request: Request,
    _auth: dict = Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Revoke tokens at Google and delete the user_integrations row."""
    user_id = request.state.user_id
    row = await get_integration(conn, user_id, _PROVIDER)
    if row is None:
        return {"ok": True}

    provider = GoogleCalendarAuth(request.app.state.pool)
    try:
        await provider.revoke(row["id"])
    except Exception:
        logger.exception("Token revocation failed for user %s", user_id)

    # Ensure deletion even if revoke had an error
    await delete_integration(conn, user_id, _PROVIDER)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 4. POST /integrations/google/sync — manual sync trigger
# ---------------------------------------------------------------------------

@router.post("/integrations/google/sync")
async def google_sync(
    request: Request,
    _auth: dict = Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Dispatch PG NOTIFY for each selected calendar. tether-sync does the work."""
    user_id = request.state.user_id
    row = await get_integration(conn, user_id, _PROVIDER)
    if row is None:
        raise HTTPException(status_code=404, detail="Google Calendar not connected")

    metadata = row.get("metadata") or {}
    calendar_ids: list[str] = metadata.get("selected_calendar_ids", ["primary"])
    integration_id = row["id"]

    for cal_id in calendar_ids:
        await dispatch_sync(
            request.app.state.pool,
            str(integration_id),
            cal_id,
            provider=_PROVIDER,
            notify_type="poll",
        )

    return {"ok": True, "dispatched": len(calendar_ids)}


# ---------------------------------------------------------------------------
# 5. POST /integrations/google/webhook — Google push notifications
# ---------------------------------------------------------------------------

@router.post("/integrations/google/webhook")
async def google_webhook(
    request: Request,
    x_goog_channel_id: str | None = Header(default=None, alias="X-Goog-Channel-Id"),
    x_goog_resource_id: str | None = Header(default=None, alias="X-Goog-Resource-Id"),
    x_goog_resource_state: str | None = Header(default=None, alias="X-Goog-Resource-State"),
):
    """Receive Google Calendar push notifications.

    Must return 200 within Google's timeout. No DB lookup here — the endpoint
    has no user context so RLS would block any integration_sync_state query.
    Instead, channel_id is forwarded in the NOTIFY payload; the tether-sync
    worker resolves it to an integration via its own unscoped DB access.
    """
    if x_goog_channel_id and x_goog_resource_state != "sync":
        await dispatch_sync(
            request.app.state.pool,
            integration_id="",   # unknown — worker resolves via channel_id
            calendar_id="",      # unknown — worker resolves via channel_id
            provider=_PROVIDER,
            notify_type="webhook",
            channel_id=x_goog_channel_id,
            resource_id=x_goog_resource_id or "",
            resource_state=x_goog_resource_state or "",
        )

    return {"ok": True}


# ---------------------------------------------------------------------------
# 6. GET /integrations/google/calendars — list user's Google calendars
# ---------------------------------------------------------------------------

@router.get("/integrations/google/calendars")
async def list_calendars(
    request: Request,
    _auth: dict = Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Fetch the user's calendar list from Google and return it."""
    user_id = request.state.user_id
    row = await get_integration(conn, user_id, _PROVIDER)
    if row is None:
        raise HTTPException(status_code=404, detail="Google Calendar not connected")

    access_token = row.get("access_token")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _GCAL_CALENDAR_LIST_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Google token expired — reconnect")
    if not resp.is_success:
        raise HTTPException(status_code=502, detail="Failed to fetch calendar list")

    data = resp.json()
    calendars = [
        {
            "id": cal.get("id"),
            "summary": cal.get("summary"),
            "primary": cal.get("primary", False),
        }
        for cal in data.get("items", [])
    ]

    metadata = row.get("metadata") or {}
    selected = metadata.get("selected_calendar_ids", ["primary"])

    return {"calendars": calendars, "selected_calendar_ids": selected}


# ---------------------------------------------------------------------------
# 7. PATCH /integrations/google/calendars — update selected calendar IDs
# ---------------------------------------------------------------------------

@router.patch("/integrations/google/calendars")
async def patch_calendars(
    request: Request,
    body: CalendarPatchBody,
    _auth: dict = Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
):
    """Update the list of calendar IDs to sync."""
    user_id = request.state.user_id
    row = await get_integration(conn, user_id, _PROVIDER)
    if row is None:
        raise HTTPException(status_code=404, detail="Google Calendar not connected")

    existing_metadata = row.get("metadata") or {}
    new_metadata = {**existing_metadata, "selected_calendar_ids": body.calendar_ids}

    updated = await upsert_integration(
        conn,
        user_id,
        _PROVIDER,
        metadata=new_metadata,
    )

    return {
        "ok": True,
        "selected_calendar_ids": (updated.get("metadata") or {}).get(
            "selected_calendar_ids", body.calendar_ids
        ),
    }
