"""Google Calendar OAuthProvider implementation.

Handles the OAuth2 flow for calendar-scoped credentials:
- get_auth_url: build the Google consent URL with state
- handle_callback: exchange code → tokens, upsert user_integrations
- refresh_token: refresh stored access token
- revoke: revoke at Google + delete from DB

OAuth state is a HMAC-SHA256-signed JSON blob carrying user_id + nonce,
base64url-encoded. This ties the callback back to the authenticated user
without relying on session cookies (which may not survive the redirect chain).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import urllib.parse
from datetime import datetime, timezone

import asyncpg
import httpx

import api.config as cfg
from db.pg_queries.integrations import (
    delete_integration,
    get_integration,
    upsert_integration,
)
from integrations.base import OAuthProvider

_PROVIDER = "google_calendar"
_SCOPES = "https://www.googleapis.com/auth/calendar.readonly"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


# ---------------------------------------------------------------------------
# State helpers (module-level so routes can import them without instantiating)
# ---------------------------------------------------------------------------

_STATE_TTL_SECONDS = 600  # 10 minutes — long enough for a slow consent screen


def make_oauth_state(user_id: str) -> str:
    """Return a signed, base64url-encoded state string carrying user_id + expiry."""
    nonce = secrets.token_hex(16)
    exp = int(datetime.now(timezone.utc).timestamp()) + _STATE_TTL_SECONDS
    payload = json.dumps(
        {"user_id": user_id, "nonce": nonce, "exp": exp}, separators=(",", ":")
    )
    sig = hmac.new(
        cfg.JWT_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    raw = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_oauth_state(state: str) -> str:
    """Verify signature and expiry; return user_id or raise ValueError."""
    try:
        raw = base64.urlsafe_b64decode(state.encode()).decode()
        payload_str, sig = raw.rsplit("|", 1)
        expected = hmac.new(
            cfg.JWT_SECRET.encode(), payload_str.encode(), hashlib.sha256
        ).hexdigest()
    except Exception:
        raise ValueError("Malformed OAuth state")
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid OAuth state signature")
    data = json.loads(payload_str)
    if int(datetime.now(timezone.utc).timestamp()) > data.get("exp", 0):
        raise ValueError("OAuth state expired")
    return data["user_id"]


# ---------------------------------------------------------------------------
# OAuthProvider implementation
# ---------------------------------------------------------------------------

class GoogleCalendarAuth(OAuthProvider):
    """OAuthProvider for Google Calendar.

    Requires a pool so handle_callback and revoke can write to Postgres.
    get_auth_url and the state helpers are pure (no DB).
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_auth_url(self, user_id: str) -> str:
        if not cfg.GOOGLE_CLIENT_ID:
            raise ValueError("GOOGLE_CLIENT_ID not configured")
        state = make_oauth_state(user_id)
        params = urllib.parse.urlencode({
            "client_id": cfg.GOOGLE_CLIENT_ID,
            "redirect_uri": cfg.GOOGLE_INTEGRATION_CALLBACK_URL,
            "response_type": "code",
            "scope": _SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

    async def handle_callback(self, user_id: str, code: str) -> None:
        """Exchange authorization code for tokens and persist them."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": cfg.GOOGLE_CLIENT_ID,
                    "client_secret": cfg.GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": cfg.GOOGLE_INTEGRATION_CALLBACK_URL,
                    "grant_type": "authorization_code",
                },
            )
        data = resp.json()
        if "error" in data:
            raise ValueError(f"Google token exchange failed: {data['error']}")

        access_token = data["access_token"]
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in", 3600)
        token_expiry = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
        )
        scopes = data.get("scope", _SCOPES).split()

        import db.postgres as pg
        async with pg.get_conn(self._pool, user_id=user_id) as conn:
            await upsert_integration(
                conn,
                user_id,
                _PROVIDER,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expiry=token_expiry,
                scopes=scopes,
                metadata={"selected_calendar_ids": ["primary"]},
            )

    async def refresh_token(self, integration_id: str) -> None:
        """Refresh the stored access token. Called by the sync worker."""
        import db.postgres as pg
        # Fetch the integration row to get refresh_token
        async with pg.get_conn(self._pool) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM user_integrations WHERE id = $1",
                integration_id,
            )
        if not row:
            raise ValueError(f"Integration {integration_id} not found")
        rt = row["refresh_token"]
        if not rt:
            raise ValueError(f"Integration {integration_id} has no refresh token")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": cfg.GOOGLE_CLIENT_ID,
                    "client_secret": cfg.GOOGLE_CLIENT_SECRET,
                    "refresh_token": rt,
                    "grant_type": "refresh_token",
                },
            )
        data = resp.json()
        if "error" in data:
            raise ValueError(f"Token refresh failed: {data['error']}")

        expires_in = data.get("expires_in", 3600)
        token_expiry = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
        )
        async with pg.get_conn(self._pool) as conn:
            await conn.execute(
                """
                UPDATE user_integrations
                SET access_token = $1, token_expiry = $2
                WHERE id = $3
                """,
                data["access_token"],
                token_expiry,
                integration_id,
            )

    async def revoke(self, integration_id: str) -> None:
        """Revoke tokens at Google and delete the integration row."""
        import db.postgres as pg
        async with pg.get_conn(self._pool) as conn:
            row = await conn.fetchrow(
                "SELECT user_id, access_token FROM user_integrations WHERE id = $1",
                integration_id,
            )
        if not row:
            return  # Already gone

        # Best-effort revocation (don't block on Google errors)
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    _REVOKE_URL,
                    params={"token": row["access_token"]},
                )
        except Exception:
            pass

        async with pg.get_conn(self._pool) as conn:
            await delete_integration(conn, str(row["user_id"]), _PROVIDER)
