"""Agent version dispatch for the Tether bot pipeline.

Routes incoming WebSocket messages to the appropriate pipeline based on the
requested agent_version:

  tether-agent-1.0 → existing JSON-mutation pipeline (handle_message)
  tether-agent-2.0 → stub notice + 1.0 fallback (not yet wired)
  tether-agent-2.5 → stub notice + 1.0 fallback (not yet wired)
  unknown / None   → treated as tether-agent-2.0 (picker default)

The stub-then-fallback pattern ensures users selecting 2.0 or 2.5 still get
a response while the real pipelines are built out. The stub is delivered via
send_fn so it joins the 1.0 response in a single chunk frame on the client
(the WS handler accumulates all send_fn calls and joins them with "\\n\\n").

Note: The Telegram polling path (bot/message_handler.py) calls handle_message
directly — it bypasses this dispatcher (Telegram has no picker UI).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from bot.message_handler import handle_message

logger = logging.getLogger(__name__)

_DEFAULT_VERSION = "tether-agent-2.0"
_STUB_VERSIONS: frozenset[str] = frozenset({"tether-agent-2.0", "tether-agent-2.5"})
_KNOWN_VERSIONS: frozenset[str] = _STUB_VERSIONS | {"tether-agent-1.0"}


def _stub_message(version: str) -> str:
    return (
        f"{version} is not yet wired up — it's coming soon. "
        "Falling back to 1.0 for this message."
    )


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
    For tether-agent-2.0/2.5 (not yet wired), sends a stub notice via send_fn
    and then falls back to the 1.0 pipeline so the user still gets a response.
    Unknown or None versions default to tether-agent-2.0 and log a warning.

    Both the stub and the 1.0 response are accumulated by the WS handler's
    capture_send_fn and joined into a single chunk frame on the client.

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

    if version in _STUB_VERSIONS:
        send_fn(_stub_message(version))
        logger.warning(
            "dispatch_message: %s not yet wired — stub sent, falling back to 1.0 user_id=%s",
            version,
            user_id,
        )

    await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)
