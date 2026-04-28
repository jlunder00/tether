"""Anthropic OAuth vault endpoints.

Endpoints:
  POST   /api/integrations/anthropic/start    -- spawn claude setup-token, return auth URL
  POST   /api/integrations/anthropic/complete -- submit code, persist credentials
  DELETE /api/integrations/anthropic          -- disconnect (delete credentials)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import auth_dependency

logger = logging.getLogger(__name__)
router = APIRouter()

# Module-level dict for pending setup states (user_id -> state dict).
# Entries older than 10 minutes are swept on each /start call.
_pending_setups: dict[str, dict] = {}

_SETUP_TTL = 600  # seconds
_URL_RE = re.compile(r"https://console\.anthropic\.com/\S+")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AnthropicCompleteBody(BaseModel):
    code: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sweep_expired_setups() -> None:
    """Kill and remove any pending setups older than _SETUP_TTL seconds."""
    now = time.time()
    expired_users = [
        uid for uid, entry in list(_pending_setups.items())
        if now - entry["started_at"] > _SETUP_TTL
    ]
    for uid in expired_users:
        entry = _pending_setups.pop(uid)
        try:
            proc = entry.get("proc")
            if proc is not None:
                proc.kill()
        except Exception:
            pass
        temp_dir = entry.get("temp_dir")
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# POST /integrations/anthropic/start
# ---------------------------------------------------------------------------

@router.post("/integrations/anthropic/start")
async def anthropic_start(
    request: Request,
    _auth: dict = Depends(auth_dependency),
):
    """Spawn `claude setup-token`, scrape the auth URL, return it to the client."""
    user_id = request.state.user_id

    _sweep_expired_setups()

    # Kill any existing pending setup for this user
    if user_id in _pending_setups:
        old = _pending_setups.pop(user_id)
        try:
            old["proc"].kill()
        except Exception:
            pass
        shutil.rmtree(old.get("temp_dir", ""), ignore_errors=True)

    temp_dir = tempfile.mkdtemp()
    env_override = {**os.environ, "CLAUDE_CONFIG_DIR": temp_dir}

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "setup-token",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_override,
        )
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.exception("Failed to spawn claude setup-token: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to spawn setup process")

    # Read stdout + stderr concurrently looking for URL, with a 10s timeout
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
    match = _URL_RE.search(combined)

    if not match:
        proc.kill()
        await proc.wait()
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=502, detail="Auth URL not found in claude output")

    url = match.group(0)

    _pending_setups[user_id] = {
        "proc": proc,
        "temp_dir": temp_dir,
        "started_at": time.time(),
    }

    return {"url": url, "expires_in": _SETUP_TTL}


# ---------------------------------------------------------------------------
# POST /integrations/anthropic/complete
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

    # Write code to stdin
    proc.stdin.write((body.code + "\n").encode())
    await proc.stdin.drain()

    # Wait for process to complete (30s timeout)
    try:
        await asyncio.wait_for(proc.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        proc.kill()
        _pending_setups.pop(user_id, None)
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=504, detail="Setup process timed out")

    if proc.returncode != 0:
        _pending_setups.pop(user_id, None)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"ok": False, "error": "setup failed"}

    # Read credentials.json from temp_dir
    creds_file = Path(temp_dir) / ".credentials.json"
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
# DELETE /integrations/anthropic
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
