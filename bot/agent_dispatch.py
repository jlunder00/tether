"""Agent version dispatch for the Tether bot pipeline.

Routes incoming WebSocket messages to the appropriate pipeline based on the
requested agent_version:

  tether-agent-1.0 → existing JSON-mutation pipeline (handle_message)
  tether-agent-2.0 → real LayerClient pipeline; 1.0 fallback on error/disabled
  tether-agent-2.5 → premium session for paid/admin users; 1.0 fallback for free
  unknown / None   → treated as tether-agent-2.0 (picker default)

The 2.0 pipeline calls the interactive-agent-layer service, which handles
streaming, tool-use translation, and permission gating. SSE events from the
layer are forwarded to the WS client via status_fn; the final response is
delivered via send_fn when turn_complete arrives.

The 2.5 pipeline routes paid users and admin users to the premium handler
(Session + Beacon + RAG). Free users receive an upgrade notice and fall back
to tether-agent-1.0. Admin users bypass the subscription check entirely.

Fallback behaviour: if the 2.0 layer is disabled (config) or unreachable
(HTTP error), dispatch silently falls back to handle_message so users always
get a response.

Note: The Telegram polling path (bot/message_handler.py) calls handle_message
directly — it bypasses this dispatcher (Telegram has no picker UI).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

import httpx

from bot.message_handler import handle_message
from config.loader import config
from interactive_agent_layer.client import LayerClient

logger = logging.getLogger(__name__)

_DEFAULT_VERSION = "tether-agent-2.0"


class _SendTracker:
    """Wraps a send_fn callback to record whether it was ever called.

    Used by _dispatch_v25 to detect whether the premium handler streamed
    any output before raising an exception.  If it did, we skip the 1.0
    fallback (handle_message) entirely to avoid double-send: the user has
    already received premium output and calling handle_message would splice
    a second, unrelated response on top of it.
    """

    def __init__(self, fn: Callable[[str], None]) -> None:
        self._fn = fn
        self.called: bool = False

    def __call__(self, text: str) -> None:
        self.called = True
        self._fn(text)


_KNOWN_VERSIONS: frozenset[str] = frozenset(
    {"tether-agent-1.0", "tether-agent-2.0", "tether-agent-2.5"}
)

# MCP tools available to tether-agent-2.0 (basic tether MCP only, no premium).
_V2_0_OPTIONS: dict[str, Any] = {
    "model": "haiku-4.5",
    "allowed_tools": [
        "upsert_tasks",
        "upsert_context",
        "delete_tasks",
        "delete_context",
        "read_context",
        "read_tasks",
        "get_plan",
        "get_anchors",
        "search",
    ],
    "max_turns": 2,
    "permission_mode": "auto",
    "mcp_servers": ["tether"],  # basic tether MCP only; no premium tools
}


def _layer_enabled() -> bool:
    """Return True if the interactive-agent-layer is enabled in config."""
    return config.get_bool("agent_layer.enabled", True)


def _stub_message(version: str) -> str:
    return (
        f"{version} is not yet wired up — it's coming soon. "
        "Falling back to 1.0 for this message."
    )


async def _dispatch_v2_0(
    text: str,
    send_fn: Callable[[str], None],
    pool: Any,
    user_id: str,
    vault: Any = None,
    status_fn: Any = None,
    event_fn: Any = None,
) -> None:
    """Run the tether-agent-2.0 pipeline via the interactive-agent-layer.

    Starts a layer session, runs one turn, and routes events:
    - agent_text_delta / unknown event types → event_fn (async, for direct WS
      forwarding; skips send_fn at turn_complete if any delta was sent)
    - status / agent_action → status_fn
    - turn_complete → send_fn(final_text) unless deltas were already streamed

    Falls back to handle_message (1.0 pipeline) when:
    - agent_layer.enabled is false in config
    - the layer service is unreachable or returns an HTTP error

    Session cleanup (end_session) is always attempted in the finally block so
    the layer doesn't hold dangling sessions on error. On asyncio cancellation,
    interrupt() is signalled before end_session so the pool can reclaim the
    subprocess quickly.
    """
    if not _layer_enabled():
        logger.info(
            "dispatch_v2_0: agent_layer disabled, falling back to 1.0 user_id=%s",
            user_id,
        )
        await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)
        return

    base_url: str = config.get("agent_layer.base_url", "http://127.0.0.1:5003")
    layer = LayerClient(base_url)
    session_id: str | None = None
    delta_sent = False

    try:
        session_id = await layer.start_session(
            user_id=user_id,
            user_ws_id=user_id,  # proxy: use user_id until per-connection IDs land
            agent_version="tether-agent-2.0",
            options=_V2_0_OPTIONS,
            user_message=text,
        )

        async for event in layer.turn(session_id, text):
            etype = event.get("type")

            if etype == "turn_complete":
                if not delta_sent:
                    send_fn(event.get("final_text", ""))
                break

            if etype == "turn_error":
                # Layer emitted an in-band error (e.g. pool exhausted) — log the
                # real cause and fall back to 1.0 so the user still gets a response.
                logger.warning(
                    "dispatch_v2_0: layer turn error, falling back to 1.0"
                    " user_id=%s: %s",
                    user_id,
                    event.get("message", "unknown"),
                )
                await handle_message(
                    text, send_fn, pool, user_id, vault=vault, status_fn=status_fn
                )
                return

            if etype in ("status", "agent_action"):
                if status_fn is not None:
                    if etype == "status":
                        msg = event.get("message", "")
                        if msg:
                            await status_fn(msg)
                    else:
                        action = event.get("action", "")
                        if action:
                            await status_fn(action)
                continue

            # agent_text_delta, permission_request, and any future event types
            # are forwarded via event_fn for direct WS delivery.
            if event_fn is not None:
                await event_fn(event)
                if etype == "agent_text_delta" and event.get("delta"):
                    delta_sent = True

    except asyncio.CancelledError:
        if session_id is not None:
            with contextlib.suppress(Exception):
                await layer.interrupt(session_id)
        raise

    except httpx.HTTPError as exc:
        # Raw transport failure (layer unreachable, connection reset mid-stream,
        # etc.) — distinct from turn_error which is an in-band error from a
        # running layer. Both fall back to 1.0 so the user still gets a response.
        logger.warning(
            "dispatch_v2_0: layer turn transport error, falling back to 1.0"
            " user_id=%s: %s",
            user_id,
            exc,
        )
        await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)

    finally:
        if session_id is not None:
            with contextlib.suppress(Exception):
                await layer.end_session(session_id)


async def _dispatch_v25(
    text: str,
    send_fn: Callable[[str], None],
    pool: Any,
    user_id: str,
    *,
    vault: Any = None,
    status_fn: Any = None,
    is_admin: bool = False,
) -> None:
    """Handle tether-agent-2.5: premium session for paid/admin users, 1.0 fallback for free.

    Paid users and admin users are routed to the premium handler (Session + Beacon + RAG).
    Admin users bypass the subscription check entirely — no subscription row required.
    Free users (non-admin, non-paid) receive an upgrade notice and fall back to tether-agent-1.0.
    If tether-premium is not installed, paid/admin users also fall back to 1.0.

    This function is a clean boundary that maps to a future HTTP endpoint in the
    self-hosted premium access plan (phase P1+).
    """
    import db.postgres as pg
    from db.pg_queries.subscriptions import get_user_is_paid

    is_paid = False
    if not is_admin:
        # Admin users skip the subscription DB check entirely.
        try:
            async with pg.get_conn(pool, user_id) as conn:
                is_paid = await get_user_is_paid(conn)
        except Exception:
            # Intentional fail-closed policy: on transient DB errors, treat the user
            # as free-tier rather than granting premium access.  Fail-open (granting
            # access on error) was explicitly rejected as a security/billing risk.
            # Sending a neutral "try again" message was also rejected because it
            # gives users no actionable path.  The 1.0 fallback ensures a response.
            logger.warning(
                "dispatch_v25: subscription check failed for user_id=%s — defaulting to free",
                user_id,
            )

    if is_admin or is_paid:
        # Wrap send_fn so we can detect whether the premium handler streamed
        # any output before raising.  If it did, we must NOT run handle_message
        # (1.0 fallback) — doing so would splice a second response on top of
        # partial premium output the user has already received.
        tracked_send = _SendTracker(send_fn)
        try:
            from tether_premium.register import get_premium_handler
            from db.pg_queries import get_anchors
            from bot.handler_utils import get_current_anchor

            async with pg.get_conn(pool, user_id) as conn:
                anchors = await get_anchors(conn)
            current_anchor = get_current_anchor(anchors)

            response = await get_premium_handler()(
                text, pool, user_id, anchors, current_anchor,
                send_fn=tracked_send, status_fn=status_fn,
            )
            if response:
                tracked_send(response)
            return
        except (ImportError, NotImplementedError):
            logger.warning(
                "dispatch_v25: premium not available for user_id=%s — falling back to 1.0",
                user_id,
            )
        except Exception:
            logger.exception(
                "dispatch_v25: premium handler raised for user_id=%s — falling back to 1.0",
                user_id,
            )

        if tracked_send.called:
            # Premium already streamed output to the user.  Skip handle_message to
            # avoid double-send.  Running handle_message here would also risk DB
            # side effects (task mutations etc.) on a message that premium already
            # partially handled.
            logger.warning(
                "dispatch_v25: premium handler streamed then raised for user_id=%s"
                " — suppressing 1.0 fallback to avoid double-send",
                user_id,
            )
            return
    else:
        send_fn(
            "tether-agent-2.5 is available on the Pro plan — you're currently on "
            "the free plan. Routing to tether-agent-1.0 for this message."
        )

    await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)


async def dispatch_message(
    agent_version: str | None,
    text: str,
    send_fn: Callable[[str], None],
    pool: Any,
    user_id: str,
    *,
    vault: Any = None,
    status_fn: Any = None,
    event_fn: Any = None,
    is_admin: bool = False,
) -> None:
    """Dispatch a user message to the correct pipeline based on agent_version.

    For tether-agent-1.0, delegates directly to handle_message with no stub.
    For tether-agent-2.0, calls the interactive-agent-layer real pipeline with
    a silent fallback to 1.0 on error or when the layer is disabled.
    For tether-agent-2.5, routes to _dispatch_v25 (paid/admin = premium; free = 1.0 fallback).
    Unknown or None versions default to tether-agent-2.0 and log a warning.

    Args:
        agent_version: The version string from the WS message, or None if absent.
        text: The user message text.
        send_fn: Callback to deliver response parts (captured by WS handler).
        pool: Database connection pool.
        user_id: Authenticated user ID.
        vault: Optional credential vault for per-user LLM auth.
        status_fn: Optional async callback for real-time status pushes.
        event_fn: Optional async callback for streamed layer events (text deltas,
            permission requests, etc.) forwarded directly to the WS client.
        is_admin: When True, bypass subscription check for 2.5 dispatch (admin users
                  have no subscription row but must reach the premium handler).
    """
    version = agent_version if agent_version in _KNOWN_VERSIONS else _DEFAULT_VERSION
    if version != agent_version:
        logger.warning(
            "dispatch_message: unknown agent_version=%r, defaulting to %s user_id=%s",
            agent_version,
            version,
            user_id,
        )

    if version == "tether-agent-1.0":
        await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)
        return

    if version == "tether-agent-2.0":
        await _dispatch_v2_0(
            text, send_fn, pool, user_id,
            vault=vault, status_fn=status_fn, event_fn=event_fn,
        )
        return

    if version == "tether-agent-2.5":
        await _dispatch_v25(
            text, send_fn, pool, user_id,
            vault=vault, status_fn=status_fn, is_admin=is_admin,
        )
        return

    # Catch-all for any future known versions not yet wired
    send_fn(_stub_message(version))
    logger.warning(
        "dispatch_message: %s not yet wired — stub sent, falling back to 1.0 user_id=%s",
        version,
        user_id,
    )
    await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)
