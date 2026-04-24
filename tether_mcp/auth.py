"""Per-connection API key auth for the MCP SSE server.

Transport      Auth mechanism
─────────────  ──────────────────────────────────────────────────
SSE (network)  X-Tether-API-Key header  OR  Authorization: Bearer <key>
               Query-param fallback intentionally omitted — keys in URLs
               appear verbatim in nginx/proxy access logs.
stdio (local)  TETHER_USER_ID env var (single-user process, trusted caller)
               The env-var fallback is NOT honoured by the HTTP middleware —
               stdio never hits ASGI, so there is no overlap.

The resolved user_id is stored in a contextvars.ContextVar so all MCP
tool handlers can read it without needing to carry a connection object
through the call stack.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Callable

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

import db.postgres as pg
from db.pg_queries.api_keys import validate_key

# Per-request resolved user_id. Falls back to None when not set.
_user_id_var: ContextVar[str | None] = ContextVar("mcp_user_id", default=None)


def get_user_id() -> str | None:
    """Return the user_id for the current MCP request.

    SSE transport: resolved from API key by middleware.
    stdio transport: falls back to TETHER_USER_ID env var (trusted local caller).
    """
    return _user_id_var.get() or os.environ.get("TETHER_USER_ID")


def _extract_key(scope: Scope) -> str | None:
    """Pull API key from X-Tether-API-Key or Authorization: Bearer header.

    Uses first-match iteration (not dict) so duplicate headers are handled
    with conventional first-wins semantics rather than silently keeping the
    last value, which could let a proxy-injected header be overridden by an
    attacker-supplied one later in the list.

    Query-param support is intentionally absent — keys in URLs appear in
    server access logs as plaintext credentials.
    """
    for name, value in scope.get("headers", []):
        if name == b"x-tether-api-key":
            key = value.decode().strip()
            if key:
                return key
        elif name == b"authorization":
            auth = value.decode().strip()
            if auth.lower().startswith("bearer "):
                candidate = auth[7:].strip()
                if candidate:
                    return candidate
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

    The TETHER_USER_ID env-var fallback is deliberately NOT applied here.
    It belongs to the stdio transport (get_user_id()) where the caller is
    a local trusted process. Applying it to HTTP would let any unauthenticated
    request resolve as the operator's account whenever the env var is set.
    """

    def __init__(self, app: ASGIApp, pool_factory: Callable) -> None:
        self.app = app
        self._pool_factory = pool_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only lifespan events bypass auth — http and websocket scopes must authenticate.
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return

        raw_key = _extract_key(scope)

        if raw_key is None:
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
