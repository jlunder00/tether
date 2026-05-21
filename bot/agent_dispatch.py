"""Agent version dispatch for the Tether bot pipeline.

Routes incoming WebSocket messages to the appropriate pipeline based on the
requested agent_version:

  tether-agent-1.0 → existing JSON-mutation pipeline (handle_message)
  tether-agent-2.0 → real LayerClient pipeline; 1.0 fallback on error/disabled
  tether-agent-2.5 → stub notice + 1.0 fallback (premium-pipeline-migrator owns this)
  unknown / None   → treated as tether-agent-2.0 (picker default)

The 2.0 pipeline calls the interactive-agent-layer service, which handles
streaming, tool-use translation, and permission gating. SSE events from the
layer are forwarded to the WS client via status_fn; the final response is
delivered via send_fn when turn_complete arrives.

Fallback behaviour: if the layer is disabled (config) or unreachable (HTTP
error), dispatch silently falls back to handle_message so users always get
a response.

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
) -> None:
    """Run the tether-agent-2.0 pipeline via the interactive-agent-layer.

    Starts a layer session, runs one turn, forwards status/action events to the
    WS client via status_fn, and delivers the final response via send_fn when
    turn_complete arrives.

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
                send_fn(event.get("final_text", ""))
                break

            if status_fn is not None:
                if etype == "status":
                    msg = event.get("message", "")
                    if msg:
                        await status_fn(msg)
                elif etype == "agent_action":
                    action = event.get("action", "")
                    if action:
                        await status_fn(action)

    except asyncio.CancelledError:
        if session_id is not None:
            with contextlib.suppress(Exception):
                await layer.interrupt(session_id)
        raise

    except httpx.HTTPError as exc:
        # Covers both start_session and turn() failures. If session_id is set,
        # the finally block cleans it up; otherwise there is nothing to end.
        logger.warning(
            "dispatch_v2_0: layer unavailable, falling back to 1.0 user_id=%s: %s",
            user_id,
            exc,
        )
        await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)

    finally:
        if session_id is not None:
            with contextlib.suppress(Exception):
                await layer.end_session(session_id)


async def dispatch_message(
    agent_version: str | None,
    text: str,
    send_fn: Callable[[str], None],
    pool: Any,
    user_id: str,
    vault: Any = None,
    status_fn: Any = None,
) -> None:
    """Dispatch a user message to the correct pipeline based on agent_version.

    For tether-agent-1.0, delegates directly to handle_message with no stub.
    For tether-agent-2.0, calls the interactive-agent-layer real pipeline with
    a silent fallback to 1.0 on error or when the layer is disabled.
    For tether-agent-2.5 (not yet wired), sends a stub notice and falls back
    to the 1.0 pipeline so the user still gets a response.
    Unknown or None versions default to tether-agent-2.0 and log a warning.

    Args:
        agent_version: The version string from the WS message, or None if absent.
        text: The user message text.
        send_fn: Callback to deliver response parts (captured by WS handler).
        pool: Database connection pool.
        user_id: Authenticated user ID.
        vault: Optional credential vault for per-user LLM auth.
        status_fn: Optional async callback for real-time status pushes.
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
        await _dispatch_v2_0(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)
        return

    # tether-agent-2.5 — stub until premium-pipeline-migrator wires the real path
    send_fn(_stub_message(version))
    logger.warning(
        "dispatch_message: %s not yet wired — stub sent, falling back to 1.0 user_id=%s",
        version,
        user_id,
    )
    await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)
