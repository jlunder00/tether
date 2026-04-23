"""Per-connection API key auth for the MCP SSE server.

Transport      Auth mechanism
─────────────  ──────────────────────────────────────────────────
SSE (network)  X-Tether-API-Key header  OR  Authorization: Bearer <key>
               Falls back to ?api_key=<key> query param for clients
               that cannot set custom headers (e.g. some SSE libraries).
stdio (local)  TETHER_USER_ID env var (single-user process, trusted caller)

The resolved user_id is stored in a contextvars.ContextVar so all MCP
tool handlers can read it without needing to carry a connection object
through the call stack.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Callable
from urllib.parse import parse_qs

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

import db.postgres as pg
from db.pg_queries.api_keys import validate_key

# Per-request resolved user_id. Falls back to None when not set.
_user_id_var: ContextVar[str | None] = ContextVar("mcp_user_id", default=None)


def get_user_id() -> str | None:
    """Return the user_id for the current MCP request.

    SSE transport: resolved from API key by middleware.
    stdio transport: falls back to TETHER_USER_ID env var.
    """
    return _user_id_var.get() or os.environ.get("TETHER_USER_ID")


def _extract_key(scope: Scope) -> str | None:
    """Pull API key from header or query string."""
    headers = dict(scope.get("headers", []))

    # X-Tether-API-Key header (preferred)
    key = headers.get(b"x-tether-api-key", b"").decode().strip()
    if key:
        return key

    # Authorization: Bearer <key>
    auth = headers.get(b"authorization", b"").decode().strip()
    if auth.lower().startswith("bearer "):
        candidate = auth[7:].strip()
        if candidate:
            return candidate

    # ?api_key=<key> query param fallback
    qs = scope.get("query_string", b"").decode()
    params = parse_qs(qs)
    candidates = params.get("api_key", [])
    if candidates:
        return candidates[0].strip()

    return None


def _make_401(message: str) -> Response:
    return Response(
        content=message,
        status_code=401,
        media_type="text/plain",
    )


class TetherAPIKeyMiddleware:
    """ASGI middleware that validates API keys for the MCP SSE server.

    Sets _user_id_var so tool handlers can call get_user_id() without
    needing request context threaded through parameters.
    """

    def __init__(self, app: ASGIApp, pool_factory: Callable) -> None:
        self.app = app
        self._pool_factory = pool_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_key = _extract_key(scope)

        if raw_key is None:
            # stdio transport doesn't hit HTTP — if we got here without a key,
            # check for the legacy env var (allows existing single-user deployments
            # to keep working without reconfiguration until they create an API key).
            env_uid = os.environ.get("TETHER_USER_ID")
            if env_uid:
                token = _user_id_var.set(env_uid)
                try:
                    await self.app(scope, receive, send)
                finally:
                    _user_id_var.reset(token)
                return
            resp = _make_401("API key required (X-Tether-API-Key header or Authorization: Bearer)")
            await resp(scope, receive, send)
            return

        pool = await self._pool_factory()
        async with pg.get_conn(pool) as conn:
            user_id = await validate_key(conn, raw_key)

        if user_id is None:
            resp = _make_401("Invalid or revoked API key")
            await resp(scope, receive, send)
            return

        token = _user_id_var.set(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _user_id_var.reset(token)
