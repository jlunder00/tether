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
import os
import re
import shutil
import tempfile
import time
import urllib.parse

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
_ANTHROPIC_URL_RE = re.compile(r"https://\S+")
# Strip ANSI CSI escape sequences emitted by TUI programs on a PTY.
# Note: does not strip OSC8 hyperlinks (\x1b]8;;URL\x07...\x1b]8;;\x07) — if
# claude setup-token ever uses them, extend this regex or post-process the URL.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# `claude setup-token` prints a long-lived OAuth token to stdout (sk-ant-oat-…)
# rather than writing a credentials file. The trailing run is URL-safe base64
# plus dashes/underscores; we capture the longest such run after the prefix.
_OAUTH_TOKEN_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]+")
_ANTHROPIC_URL_SCHEME = "https"
# claude setup-token may emit URLs on either domain depending on version.
_VALID_ANTHROPIC_NETLOCS = {"console.anthropic.com", "claude.com"}
_OAUTH_TOKEN_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]+")


def _extract_anthropic_url(text: str) -> str | None:
    """Extract and strictly validate the Anthropic auth URL from subprocess output.

    Strips CR/LF before matching so PTY line-wrapping doesn't split the URL.
    Uses urlparse to check scheme and netloc exactly — prevents substring-match
    bypasses where a valid domain appears at an arbitrary position in a crafted URL.
    """
    # PTY output uses CRLF; strip both so the URL regex can match across wrap points.
    joined = text.replace("\r", "").replace("\n", "")
    for match in _ANTHROPIC_URL_RE.finditer(joined):
        candidate = match.group(0).rstrip(".,;)")  # strip trailing punctuation
        parsed = urllib.parse.urlparse(candidate)
        if parsed.scheme == _ANTHROPIC_URL_SCHEME and parsed.netloc in _VALID_ANTHROPIC_NETLOCS:
            return candidate
    return None


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

def _close_child_sync(child) -> None:
    """Kill a pexpect child and close its PTY file descriptor."""
    try:
        child.close(force=True)
    except Exception:
        pass


async def _reap_child(child) -> None:
    """Async wrapper: close pexpect child in an executor to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _close_child_sync, child)
    except Exception:
        pass


def _start_pexpect_sync(temp_dir: str, env: dict) -> tuple:
    """Spawn ``claude setup-token`` in a PTY, wait for the auth URL, return ``(child, url)``.

    The child process stays alive after this returns, waiting for the user to
    paste the OAuth code via :func:`_complete_pexpect_sync`.

    A wide PTY (220 cols) prevents the URL from line-wrapping, which would
    break the URL regex. Returns ``(None, None)`` on any failure.
    """
    import pexpect  # lazy — keeps module importable when pexpect is not installed

    logger.info("anthropic/start: spawning claude setup-token in temp_dir=%s", temp_dir)
    try:
        child = pexpect.spawn(
            "claude",
            args=["setup-token"],
            env=env,
            dimensions=(24, 500),
        )
        logger.debug("anthropic/start: pexpect.spawn ok, pid=%s", child.pid)
    except Exception:
        logger.exception("pexpect.spawn failed for claude setup-token")
        return None, None

    buf = ""
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            chunk = child.read_nonblocking(4096, timeout=1)
            # Accumulate raw bytes first, then strip ANSI from the full buffer
            # so CSI sequences that straddle read boundaries are handled correctly.
            buf += chunk.decode(errors="replace")
            clean = _ANSI_ESCAPE_RE.sub("", buf)
            logger.debug("anthropic/start: pexpect buffer so far (clean): %r", clean[-500:])
            url = _extract_anthropic_url(clean)
            if url:
                logger.info("anthropic/start: auth URL extracted: %s", url)
                return child, url
        except pexpect.TIMEOUT:
            continue
        except pexpect.EOF:
            logger.warning(
                "anthropic/start: pexpect EOF before URL found; full output: %r",
                _ANSI_ESCAPE_RE.sub("", buf),
            )
            break
        except Exception:
            logger.exception("Unexpected error reading pexpect child output")
            break

    logger.error(
        "anthropic/start: gave up waiting for auth URL after 30s; "
        "last buffer (clean, last 500 chars): %r",
        _ANSI_ESCAPE_RE.sub("", buf)[-500:],
    )
    _close_child_sync(child)
    return None, None


def _complete_pexpect_sync(child, code: str) -> tuple[str, str]:
    """Send the OAuth code to the waiting pexpect child and capture the OAuth token.

    Streams child output live (one INFO log per chunk) so we can see exactly
    what the CLI emits after the code is sent. Scans each chunk for the token
    pattern so we catch it as soon as it appears rather than waiting for EOF.

    Returns a (result, token) tuple where result is one of:
      ``"ok"``      — token found; token string is non-empty
      ``"failed"``  — child exited without printing a token
      ``"timeout"`` — 120 seconds elapsed without token or EOF
      ``"error"``   — unexpected error
    """
    import pexpect  # lazy — keeps module importable when pexpect is not installed

    logger.info("anthropic/complete: sending code (length=%d) to pexpect child", len(code))
    try:
        child.send(code + '\r')  # \r alone = one Enter in PTY canonical mode
    except Exception:
        logger.exception("pexpect send failed — child likely already exited")
        return "error", ""

    buf = b""
    token: str | None = None
    sent_confirm = False
    deadline = time.time() + 120

    while time.time() < deadline:
        try:
            chunk = child.read_nonblocking(4096, timeout=1)
            buf += chunk
            clean = _ANSI_ESCAPE_RE.sub("", chunk.decode(errors="replace"))
            safe = _OAUTH_TOKEN_RE.sub("sk-ant-***REDACTED***", clean)
            logger.info("anthropic/complete: child output chunk: %r", safe)
            match = _OAUTH_TOKEN_RE.search(clean)
            if match:
                token = match.group(0)
                logger.info("anthropic/complete: token found in output stream")
                break
            # After the code echo the CLI may sit at a secondary "press Enter"
            # prompt.  Detect the two-blank-line pattern that follows the
            # asterisk echo and send a confirming \r once.
            if not sent_confirm and b"\r\r\n\r\r\n" in buf:
                logger.info("anthropic/complete: sending confirm \\r after code echo")
                child.send('\r')
                sent_confirm = True
        except pexpect.TIMEOUT:
            continue
        except pexpect.EOF:
            logger.info("anthropic/complete: child EOF")
            # Token may have arrived in the same read as EOF — scan full buffer.
            full_clean = _ANSI_ESCAPE_RE.sub("", buf.decode(errors="replace"))
            match = _OAUTH_TOKEN_RE.search(full_clean)
            if match:
                token = match.group(0)
                logger.info("anthropic/complete: token found at EOF")
            break
        except Exception:
            logger.exception("pexpect read_nonblocking failed")
            return "error", ""
    else:
        full_clean = _ANSI_ESCAPE_RE.sub("", buf.decode(errors="replace"))
        logger.warning(
            "anthropic/complete: timed out waiting for token; output so far: %r",
            full_clean[-500:],
        )
        return "timeout", ""

    try:
        child.close()
    except Exception:
        pass

    if token:
        return "ok", token
    logger.warning(
        "anthropic/complete: child exited without printing token; full output: %r",
        _ANSI_ESCAPE_RE.sub("", buf.decode(errors="replace"))[-500:],
    )
    return "failed", ""


async def _sweep_expired_setups() -> None:
    """Kill and remove any pending setups older than _SETUP_TTL seconds.

    Each killed child is reaped via an asyncio task so PTY FDs are released
    without blocking the current request.
    """
    now = time.time()
    expired_users = [
        uid for uid, entry in list(_pending_setups.items())
        if now - entry["started_at"] > _SETUP_TTL
    ]
    for uid in expired_users:
        entry = _pending_setups.pop(uid)
        child = entry.get("child")
        if child is not None:
            asyncio.create_task(_reap_child(child))
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

    Spawns ``claude setup-token`` in a PTY via :func:`_start_pexpect_sync` (run
    in a thread-pool executor so the event loop is not blocked). The pexpect child
    stays alive waiting for the user to paste their OAuth code.
    """
    logger.info("anthropic/start: request for user_id=%s", user_id)

    if user_id in _pending_setups:
        logger.info("anthropic/start: killing existing pending setup for user_id=%s", user_id)
        old = _pending_setups.pop(user_id)
        asyncio.create_task(_reap_child(old["child"]))
        shutil.rmtree(old.get("temp_dir", ""), ignore_errors=True)

    temp_dir = tempfile.mkdtemp()
    logger.debug("anthropic/start: created temp_dir=%s for user_id=%s", temp_dir, user_id)
    env_override = {**os.environ, "CLAUDE_CONFIG_DIR": temp_dir}

    loop = asyncio.get_running_loop()
    try:
        child, url = await loop.run_in_executor(
            None, _start_pexpect_sync, temp_dir, env_override
        )
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.exception("Unexpected error from _start_pexpect_sync: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to spawn setup process")

    if url is None:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.error("anthropic/start: failed to extract auth URL for user_id=%s", user_id)
        raise HTTPException(status_code=502, detail="Auth URL not found in claude output")

    _pending_setups[user_id] = {
        "child": child,
        "temp_dir": temp_dir,
        "started_at": time.time(),
    }
    logger.info("anthropic/start: success, auth URL ready for user_id=%s", user_id)

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
    """Submit the OAuth code to the waiting pexpect child and persist credentials."""
    user_id = request.state.user_id
    logger.info("anthropic/complete: request for user_id=%s, code_length=%d", user_id, len(body.code))

    # Pop atomically: prevents two concurrent /complete calls from racing on the
    # same child process or temp dir.
    entry = _pending_setups.pop(user_id, None)
    if entry is None:
        logger.warning("anthropic/complete: no pending setup found for user_id=%s", user_id)
        raise HTTPException(status_code=404, detail="No pending Anthropic setup for this user")

    child = entry["child"]
    temp_dir = entry["temp_dir"]
    age = time.time() - entry["started_at"]
    logger.debug("anthropic/complete: pending setup age=%.1fs temp_dir=%s", age, temp_dir)

    loop = asyncio.get_running_loop()
    result, token = await loop.run_in_executor(None, _complete_pexpect_sync, child, body.code)
    logger.info("anthropic/complete: pexpect result=%r for user_id=%s", result, user_id)

    if result == "error":
        asyncio.create_task(_reap_child(child))
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=502, detail="Setup process closed unexpectedly")

    if result == "timeout":
        asyncio.create_task(_reap_child(child))
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=504, detail="Setup process timed out")

    # child already reaped by _complete_pexpect_sync.
    if result == "failed":
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.warning("anthropic/complete: setup process reported failure for user_id=%s", user_id)
        return {"ok": False, "error": "setup failed"}

    # result == "ok": token was extracted from the output stream by _complete_pexpect_sync.
    logger.debug("anthropic/complete: OAuth token extracted (len=%d)", len(token))

    vault = request.app.state.vault
    if vault is None:
        logger.error("anthropic/complete: vault is None — credentials cannot be persisted for user_id=%s", user_id)
    else:
        await vault.store_initial(user_id, {"oauth_token": token})
        logger.info("anthropic/complete: credentials stored in vault for user_id=%s", user_id)

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
