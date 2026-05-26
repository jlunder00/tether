"""Integration routes — Google Calendar + Anthropic OAuth vault.

Google Calendar endpoints (all under /api/integrations/google/):
  GET  /connect      — initiate OAuth, redirect to Google consent
  GET  /callback     — exchange code, store tokens (unauthenticated — comes from Google)
  POST /disconnect   — revoke tokens + delete integration
  POST /sync         — manual sync trigger via PG NOTIFY
  POST /webhook      — receive Google push notifications (must return 200 fast)
  GET  /calendars    — list user's calendars from Google API
  PATCH /calendars   — update selected calendar IDs in metadata

Anthropic OAuth vault endpoints:
  POST   /integrations/anthropic/start    — spawn claude setup-token, return auth URL
  POST   /integrations/anthropic/complete — submit code, persist credentials
  DELETE /integrations/anthropic          — disconnect (delete credentials blob)
"""
from __future__ import annotations

import asyncio
import logging
import time

import asyncpg
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

import api.config as cfg
from api.auth import auth_dependency
from db.pg_queries.integrations import (
    delete_integration,
    delete_tasks_by_source,
    get_integration,
    upsert_integration,
)
from db.pool_middleware import get_db_conn
from integrations.google_calendar.auth import (
    GoogleCalendarAuth,
    verify_oauth_state,
)
from integrations.google_calendar.sync import GoogleCalendarSync
from integrations.models import WebhookPayload
from sync.dispatch import dispatch_sync  # re-exported so tests can monkeypatch at this name

logger = logging.getLogger(__name__)
router = APIRouter()

_PROVIDER = "google_calendar"
_GCAL_CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"

# ---------------------------------------------------------------------------
# Anthropic OAuth vault — module-level state
# ---------------------------------------------------------------------------

# Registry of pending claude setup-token processes keyed by user_id.
# Entries older than _SETUP_TTL seconds are swept on each /start call.
_pending_setups: dict[str, dict] = {}

# Per-user locks to prevent concurrent /start races.
_start_locks: dict[str, asyncio.Lock] = {}

_SETUP_TTL = 600  # seconds
# Pool manager base URL — pexpect subprocess work is delegated to this service.
_POOL_MANAGER_BASE_URL = "http://127.0.0.1:5002"



# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CalendarPatchBody(BaseModel):
    calendar_ids: list[str]


class AnthropicCompleteBody(BaseModel):
    code: str




async def _sweep_expired_setups() -> None:
    """Remove pending setup entries older than _SETUP_TTL seconds.

    Session cleanup on the pool manager side is handled by the pool manager
    itself; this sweep only removes stale session_id references from our
    local ``_pending_setups`` dict.
    """
    now = time.time()
    expired_users = [
        uid for uid, entry in list(_pending_setups.items())
        if now - entry["started_at"] > _SETUP_TTL
    ]
    for uid in expired_users:
        _pending_setups.pop(uid, None)
        logger.debug("anthropic/sweep: removed expired setup for user_id=%s", uid)


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

async def _initial_sync_and_register(pool: asyncpg.Pool, user_id: str) -> None:
    """Background task fired immediately after OAuth callback completes.

    For each selected calendar (default ``["primary"]``):
      * dispatches an initial poll sync via PG NOTIFY so events appear right away,
      * registers a Google push-notification webhook so future changes flow in.

    Webhook registration is best-effort — the dev tunnel may be down, and
    failure must not prevent the initial sync from running. Sync dispatch
    failures are also caught per-calendar so one bad calendar can't starve
    the rest.
    """
    import db.postgres as pg

    async with pg.get_conn(pool, user_id=user_id) as conn:
        row = await get_integration(conn, user_id, _PROVIDER)

    if row is None:
        logger.info(
            "initial_sync_and_register: no integration row for user %s; skipping",
            user_id,
        )
        return

    integration_id = str(row["id"])
    metadata = row.get("metadata") or {}
    calendar_ids: list[str] = metadata.get("selected_calendar_ids", ["primary"])

    sync_provider = GoogleCalendarSync(pool)

    for calendar_id in calendar_ids:
        try:
            await dispatch_sync(
                pool,
                integration_id,
                calendar_id,
                provider=_PROVIDER,
                notify_type="poll",
            )
        except Exception:
            logger.exception(
                "initial_sync_and_register: dispatch_sync failed for %s/%s",
                integration_id,
                calendar_id,
            )

        try:
            await sync_provider.register_webhook(integration_id, calendar_id)
        except Exception:
            # Webhook registration is best-effort: dev tunnel may be down,
            # Google may rate-limit, etc. Log and continue.
            logger.warning(
                "initial_sync_and_register: register_webhook failed for %s/%s "
                "(continuing — initial poll sync still scheduled)",
                integration_id,
                calendar_id,
                exc_info=True,
            )


@router.get("/integrations/google/callback")
async def google_callback(
    request: Request,
    code: str,
    state: str,
    background_tasks: BackgroundTasks,
):
    """Exchange authorization code for tokens and persist them.

    User identity is recovered from the signed `state` parameter — no cookie
    is reliably available on this cross-site redirect.

    After persisting tokens, schedules a background task that fires the
    initial sync and registers the Google push webhook. The redirect to
    /plan/day is not blocked on either operation.
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

    background_tasks.add_task(
        _initial_sync_and_register,
        request.app.state.pool,
        user_id,
    )

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

    # Delete all tasks synced from this integration before removing the row
    deleted = await delete_tasks_by_source(conn, user_id, _PROVIDER)
    logger.info("disconnect: deleted %d synced tasks for user %s", deleted, user_id)

    # Ensure integration row deletion even if revoke had an error
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

async def _process_gcal_event(
    channel_id: str | None,
    resource_state: str | None,
    pool,
) -> None:
    """BackgroundTask: process an inbound Google Calendar push notification inline.

    Replaces the former PG NOTIFY → tether-sync worker hop. The HTTP request
    itself wakes the Fly.io machine; syncing inline means no persistent LISTEN
    connection is needed.

    resource_state="sync" is Google's registration ping — safe to ignore.
    An unknown channel_id (no matching integration_sync_state row) is logged
    and discarded; it could mean a channel that expired and was re-registered
    under a new ID, or a stale notification after disconnect.
    """
    if not channel_id or resource_state == "sync":
        return

    import db.postgres as pg

    # Resolve channel_id → integration_id via an unscoped connection.
    # integration_sync_state is a background-system table; no user context needed.
    async with pg.get_conn(pool) as conn:
        row = await conn.fetchrow(
            "SELECT integration_id FROM integration_sync_state WHERE watch_channel_id = $1",
            channel_id,
        )

    if not row:
        logger.warning(
            "_process_gcal_event: no sync state for channel_id=%s; ignoring",
            channel_id,
        )
        return

    integration_id = str(row["integration_id"])
    payload = WebhookPayload(
        channel_id=channel_id,
        resource_id="",
        resource_state=resource_state or "",
        raw_headers={},
    )

    provider = GoogleCalendarSync(pool)
    try:
        await provider.handle_webhook(integration_id, payload)
    except Exception:
        logger.exception(
            "_process_gcal_event: error handling channel_id=%s integration_id=%s",
            channel_id,
            integration_id,
        )


@router.post("/integrations/google/webhook")
async def google_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_goog_channel_id: str | None = Header(default=None, alias="X-Goog-Channel-Id"),
    x_goog_resource_state: str | None = Header(default=None, alias="X-Goog-Resource-State"),
):
    """Receive Google Calendar push notifications.

    Returns 200 immediately; sync is dispatched as a BackgroundTask so the
    response is never delayed by DB or Google API latency. The Fly.io machine
    wakes on this HTTP request, making a persistent PG LISTEN connection
    unnecessary.
    """
    background_tasks.add_task(
        _process_gcal_event,
        x_goog_channel_id,
        x_goog_resource_state,
        request.app.state.pool,
    )
    return Response(status_code=200)


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


# ---------------------------------------------------------------------------
# 8. GET /integrations/anthropic — connection status
# ---------------------------------------------------------------------------

@router.get("/integrations/anthropic")
async def anthropic_status(
    request: Request,
    _auth: dict = Depends(auth_dependency),
):
    """Return whether the authenticated user has Anthropic credentials stored."""
    user_id = request.state.user_id
    vault = request.app.state.vault
    connected = await vault.is_connected(user_id) if vault is not None else False
    return {"connected": connected}


# ---------------------------------------------------------------------------
# 9. POST /integrations/anthropic/start
# ---------------------------------------------------------------------------

@router.post("/integrations/anthropic/start")
async def anthropic_start(
    request: Request,
    _auth: dict = Depends(auth_dependency),
):
    """Spawn `claude setup-token`, scrape the auth URL, return it to the client."""
    user_id = request.state.user_id

    await _sweep_expired_setups()

    # Serialize concurrent /start calls per user to prevent subprocess leaks.
    lock = _start_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        return await _anthropic_start_locked(request, user_id)


async def _anthropic_start_locked(request: Request, user_id: str) -> dict:
    """Inner /start logic — called while holding the per-user _start_locks entry.

    Proxies to the agent pool manager's POST /setup-token endpoint, which
    spawns ``claude setup-token`` in a PTY and returns the auth URL and a
    session_id.  The session_id is stored in ``_pending_setups`` so the
    /complete handler can forward the OAuth code to the correct subprocess.
    """
    logger.info("anthropic/start: request for user_id=%s", user_id)

    if user_id in _pending_setups:
        old_entry = _pending_setups.pop(user_id)
        old_session_id = old_entry.get("session_id")
        logger.info(
            "anthropic/start: canceling stale pending setup for user_id=%s session_id=%s",
            user_id, old_session_id,
        )
        if old_session_id:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.delete(f"{_POOL_MANAGER_BASE_URL}/setup-token/{old_session_id}")
            except Exception:
                logger.warning(
                    "anthropic/start: failed to cancel stale session_id=%s (continuing)",
                    old_session_id,
                    exc_info=True,
                )

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(f"{_POOL_MANAGER_BASE_URL}/setup-token", json={})
    except Exception as exc:
        logger.exception("anthropic/start: pool manager request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach setup-token service")

    if resp.status_code != 200:
        logger.error(
            "anthropic/start: pool manager returned %d for user_id=%s body=%r",
            resp.status_code, user_id, resp.text,
        )
        raise HTTPException(status_code=502, detail="Auth URL not found in claude output")

    data = resp.json()
    session_id = data.get("session_id")
    url = data.get("url")

    if not session_id or not url:
        logger.error("anthropic/start: pool manager response missing fields: %r", data)
        raise HTTPException(status_code=502, detail="Invalid response from setup-token service")

    _pending_setups[user_id] = {
        "session_id": session_id,
        "started_at": time.time(),
    }
    logger.info("anthropic/start: success, auth URL ready for user_id=%s session_id=%s", user_id, session_id)

    return {"url": url, "expires_in": _SETUP_TTL}


# ---------------------------------------------------------------------------
# 9. POST /integrations/anthropic/complete
# ---------------------------------------------------------------------------

@router.post("/integrations/anthropic/complete")
async def anthropic_complete(
    request: Request,
    body: AnthropicCompleteBody,
    _auth: dict = Depends(auth_dependency),
):
    """Forward the OAuth code to the pool manager and persist the returned token."""
    user_id = request.state.user_id
    logger.info("anthropic/complete: request for user_id=%s, code_length=%d", user_id, len(body.code))

    entry = _pending_setups.pop(user_id, None)
    if entry is None:
        logger.warning("anthropic/complete: no pending setup found for user_id=%s", user_id)
        raise HTTPException(status_code=404, detail="No pending Anthropic setup for this user")

    session_id = entry["session_id"]
    age = time.time() - entry["started_at"]
    logger.debug("anthropic/complete: pending setup age=%.1fs session_id=%s", age, session_id)

    try:
        async with httpx.AsyncClient(timeout=150.0) as client:
            resp = await client.post(
                f"{_POOL_MANAGER_BASE_URL}/setup-token/complete",
                json={"session_id": session_id, "code": body.code},
            )
    except Exception as exc:
        logger.exception("anthropic/complete: pool manager request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach setup-token service")

    if resp.status_code != 200:
        logger.error(
            "anthropic/complete: pool manager returned %d for user_id=%s body=%r",
            resp.status_code, user_id, resp.text,
        )
        raise HTTPException(status_code=502, detail="Setup token completion failed")

    data = resp.json()
    result = data.get("result")
    token = data.get("token") or ""
    logger.info("anthropic/complete: pool manager result=%r for user_id=%s", result, user_id)

    if result == "error":
        raise HTTPException(status_code=502, detail="Setup process closed unexpectedly")

    if result == "timeout":
        raise HTTPException(status_code=504, detail="Setup process timed out")

    if result == "failed":
        logger.warning("anthropic/complete: setup process reported failure for user_id=%s", user_id)
        return {"ok": False, "error": "setup failed"}

    # result == "ok": token extracted by the pool manager's pexpect handler.
    logger.debug("anthropic/complete: OAuth token received (len=%d)", len(token))

    vault = request.app.state.vault
    if vault is None:
        logger.error("anthropic/complete: vault is None — credentials cannot be persisted for user_id=%s", user_id)
    else:
        await vault.store_initial(user_id, {"oauth_token": token})
        logger.info("anthropic/complete: credentials stored in vault for user_id=%s", user_id)

    return {"ok": True}


# ---------------------------------------------------------------------------
# 10. DELETE /integrations/anthropic
# ---------------------------------------------------------------------------

@router.delete("/integrations/anthropic")
async def anthropic_disconnect(
    request: Request,
    _auth: dict = Depends(auth_dependency),
):
    """Delete the Anthropic credentials blob for the authenticated user."""
    user_id = request.state.user_id
    vault = request.app.state.vault
    if vault is not None:
        await vault.disconnect(user_id)
    return {"ok": True}
