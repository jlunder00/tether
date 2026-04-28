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
import json
import logging
import os
import pathlib
import re
import shutil
import tempfile
import time

import asyncpg
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
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
_ANTHROPIC_URL_RE = re.compile(r"https://console\.anthropic\.com/\S+")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CalendarPatchBody(BaseModel):
    calendar_ids: list[str]


class AnthropicCompleteBody(BaseModel):
    code: str


# ---------------------------------------------------------------------------
# Anthropic OAuth helpers
# ---------------------------------------------------------------------------

async def _reap_proc(proc) -> None:
    """Kill a subprocess and await it to release transport/pipe FDs."""
    try:
        proc.kill()
    except Exception:
        pass
    try:
        await proc.wait()
    except Exception:
        pass


async def _sweep_expired_setups() -> None:
    """Kill and remove any pending setups older than _SETUP_TTL seconds.

    Each killed process is reaped via an asyncio task so pipe FDs are released
    without blocking the current request.
    """
    now = time.time()
    expired_users = [
        uid for uid, entry in list(_pending_setups.items())
        if now - entry["started_at"] > _SETUP_TTL
    ]
    for uid in expired_users:
        entry = _pending_setups.pop(uid)
        proc = entry.get("proc")
        if proc is not None:
            asyncio.create_task(_reap_proc(proc))
        temp_dir = entry.get("temp_dir")
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


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


# ---------------------------------------------------------------------------
# 8. POST /integrations/anthropic/start
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
    """Inner /start logic — called while holding the per-user _start_locks entry."""
    if user_id in _pending_setups:
        old = _pending_setups.pop(user_id)
        asyncio.create_task(_reap_proc(old["proc"]))
        shutil.rmtree(old.get("temp_dir", ""), ignore_errors=True)

    temp_dir = tempfile.mkdtemp()
    env_override = {**os.environ, "CLAUDE_CONFIG_DIR": temp_dir}

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "setup-token",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            env=env_override,
        )
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.exception("Failed to spawn claude setup-token: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to spawn setup process")

    async def _read_stream(stream):
        try:
            return await asyncio.wait_for(stream.read(65536), timeout=10.0)
        except asyncio.TimeoutError:
            return b""

    stdout_bytes, stderr_bytes = await asyncio.gather(
        _read_stream(proc.stdout),
        _read_stream(proc.stderr),
    )

    combined = stdout_bytes.decode(errors="replace") + stderr_bytes.decode(errors="replace")
    match = _ANTHROPIC_URL_RE.search(combined)

    if not match:
        proc.kill()
        await proc.wait()
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=502, detail="Auth URL not found in claude output")

    _pending_setups[user_id] = {
        "proc": proc,
        "temp_dir": temp_dir,
        "started_at": time.time(),
    }

    return {"url": match.group(0), "expires_in": _SETUP_TTL}


# ---------------------------------------------------------------------------
# 9. POST /integrations/anthropic/complete
# ---------------------------------------------------------------------------

@router.post("/integrations/anthropic/complete")
async def anthropic_complete(
    request: Request,
    body: AnthropicCompleteBody,
    _auth: dict = Depends(auth_dependency),
):
    """Submit the OAuth code to the waiting subprocess and persist credentials."""
    user_id = request.state.user_id

    entry = _pending_setups.get(user_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No pending Anthropic setup for this user")

    proc = entry["proc"]
    temp_dir = entry["temp_dir"]

    # Write code to subprocess stdin — guard against broken pipe if process already exited.
    try:
        proc.stdin.write((body.code + "\n").encode())
        await asyncio.wait_for(proc.stdin.drain(), timeout=5.0)
    except (BrokenPipeError, ConnectionResetError, asyncio.TimeoutError, OSError) as exc:
        _pending_setups.pop(user_id, None)
        asyncio.create_task(_reap_proc(proc))
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.warning("anthropic_complete: stdin write failed (%s)", exc)
        raise HTTPException(status_code=502, detail="Setup process closed unexpectedly")

    try:
        await asyncio.wait_for(proc.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        _pending_setups.pop(user_id, None)
        asyncio.create_task(_reap_proc(proc))
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=504, detail="Setup process timed out")

    if proc.returncode != 0:
        _pending_setups.pop(user_id, None)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"ok": False, "error": "setup failed"}

    creds_file = pathlib.Path(temp_dir) / ".credentials.json"
    if not creds_file.exists():
        _pending_setups.pop(user_id, None)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"ok": False, "error": "credentials file not found"}

    blob_dict = json.loads(creds_file.read_text())

    vault = request.app.state.vault
    if vault is not None:
        await vault.store_initial(user_id, blob_dict)

    _pending_setups.pop(user_id, None)
    shutil.rmtree(temp_dir, ignore_errors=True)

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
