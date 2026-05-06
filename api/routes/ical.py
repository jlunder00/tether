"""iCal/ICS import endpoint.

POST /ical/import
  - multipart/form-data with `file` field  (file upload)
  - application/json with `{"url": "..."}` (URL fetch)

Returns:
  {"imported": N, "updated": N, "skipped": N, "errors": [...], "total_events": N}
"""
from __future__ import annotations

import ipaddress
import logging
import socket

import asyncpg
import httpx
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, HttpUrl

from api.auth import auth_dependency
from db.pg_queries.tasks import upsert_task_from_draft
from db.pool_middleware import get_db_conn

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
_URL_FETCH_TIMEOUT = 10.0           # seconds

# Private/link-local CIDR ranges blocked for SSRF prevention
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),          # unique-local IPv6
    ipaddress.ip_network("fe80::/10"),         # link-local IPv6
]


class ICalUrlBody(BaseModel):
    url: HttpUrl


def _is_private_address(hostname: str) -> bool:
    """Return True if *hostname* resolves to any private/link-local address."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False  # can't resolve → not our problem to block
    for info in infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                return True
    return False


async def _fetch_url(url: str) -> bytes:
    """Fetch ICS content from a URL with SSRF protection and size limit."""
    parsed = httpx.URL(url)
    if _is_private_address(parsed.host):
        raise HTTPException(status_code=422, detail="URL targets a private address")

    try:
        async with httpx.AsyncClient(timeout=_URL_FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail="Timed out fetching URL")
    except httpx.RequestError as exc:
        logger.warning("URL fetch failed for %s: %s", url, exc)
        raise HTTPException(status_code=502, detail="Failed to fetch URL — check the address and try again")

    if not resp.is_success:
        raise HTTPException(
            status_code=502,
            detail=f"URL returned HTTP {resp.status_code} — it may require authentication",
        )

    content = resp.content
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Remote ICS file exceeds 5 MB limit")
    return content


@router.post("/ical/import", status_code=200)
async def import_ical(
    request: Request,
    _auth: dict = Depends(auth_dependency),
    conn: asyncpg.Connection = Depends(get_db_conn),
    file: UploadFile | None = File(default=None),
    skip_all_day: bool = Query(default=False),
):
    """Import events from an ICS file or URL.

    Accepts:
      - multipart/form-data: `file` field containing the .ics bytes
      - application/json: `{"url": "..."}` body to fetch remotely

    Returns a summary of imported, updated, skipped, and errored events.
    """
    from integrations.ical.parser import parse_ics_bytes

    # ── Resolve raw ICS bytes ────────────────────────────────────────────────
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        if file is None:
            raise HTTPException(status_code=422, detail="Missing 'file' field in multipart form")
        raw = await file.read(_MAX_FILE_BYTES + 1)
        if len(raw) > _MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="ICS file exceeds 5 MB limit")

    elif "application/json" in content_type:
        try:
            body_bytes = await request.body()
            import json as _json
            body_data = _json.loads(body_bytes)
            url_body = ICalUrlBody(**body_data)
        except Exception:
            raise HTTPException(status_code=422, detail="Expected JSON body with 'url' field")
        raw = await _fetch_url(str(url_body.url))

    else:
        # Fallback: try to read a raw body (e.g. Content-Type: text/calendar)
        raw = await request.body()
        if len(raw) > _MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="ICS file exceeds 5 MB limit")
        if not raw:
            raise HTTPException(
                status_code=422,
                detail="Send multipart/form-data with a 'file' field, or application/json with a 'url' field",
            )

    # ── Parse ────────────────────────────────────────────────────────────────
    try:
        drafts, parse_errors = parse_ics_bytes(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    total_events = len(drafts) + len(parse_errors)
    warning: str | None = None
    if total_events >= 1000 and len(parse_errors) == 0:
        # parse_ics_bytes caps at 1000; if we got exactly 1000 the file may have had more
        warning = "File may contain more than 1000 events; only the first 1000 were imported"

    # ── Upsert ───────────────────────────────────────────────────────────────
    user_id = request.state.user_id
    n_imported = 0
    n_updated = 0
    n_skipped = 0
    upsert_errors: list[dict] = list(parse_errors)  # include parse failures in errors output

    for draft in drafts:
        # Skip cancelled events that don't have an existing row to update
        # (the upsert will handle cancelled events that do exist — sets source_status)
        if draft.source_status == "cancelled":
            n_skipped += 1
            continue

        # Optionally skip all-day events (no time component — start at midnight UTC)
        if skip_all_day and draft.start_time and draft.end_time:
            from datetime import time as _time, timezone as _tz
            midnight = _time(0, 0, 0)
            is_midnight_start = (
                draft.start_time.astimezone(_tz.utc).time() == midnight
            )
            if is_midnight_start:
                n_skipped += 1
                continue

        try:
            # Use a savepoint per event so a single failure doesn't abort the
            # outer connection-level transaction — other events can still succeed.
            async with conn.transaction():
                row = await upsert_task_from_draft(conn, user_id, draft)
            # Version > 0 means the row already existed (updated); 0 means fresh insert.
            if row.get("version", 0) > 0:
                n_updated += 1
            else:
                n_imported += 1
        except Exception as exc:
            logger.warning("upsert failed for event %s: %s", draft.external_id, exc, exc_info=True)
            # Include exception class name only — no message to avoid leaking DB internals.
            upsert_errors.append({"uid": draft.external_id, "error": f"Failed to save event ({type(exc).__name__})"})

    result: dict = {
        "imported": n_imported,
        "updated": n_updated,
        "skipped": n_skipped,
        "errors": upsert_errors,
        "total_events": total_events,
    }
    if warning:
        result["warning"] = warning
    return result
