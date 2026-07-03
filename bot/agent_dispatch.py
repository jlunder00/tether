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
    "model": "claude-haiku-4-5-20251001",
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
    conversation_id: str | None = None,
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

    # Inject the user's OAuth token so the pool subprocess can authenticate.
    # Never mutate _V2_0_OPTIONS; always copy.
    if vault is None:
        logger.error(
            "dispatch_v2_0: vault is not configured — VAULT_KEY must be set. "
            "Falling back to 1.0 pipeline for user_id=%s",
            user_id,
        )
        await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)
        return

    try:
        async with vault.materialize(user_id) as env_dict:
            options: dict[str, Any] = {**_V2_0_OPTIONS, "env": dict(env_dict)}
    except ValueError:
        logger.warning(
            "dispatch_v2_0: no vault credentials for user_id=%s"
            " — user must connect Anthropic account. Falling back to 1.0 pipeline.",
            user_id,
        )
        await handle_message(text, send_fn, pool, user_id, vault=vault, status_fn=status_fn)
        return

    try:
        session_id = await layer.start_session(
            user_id=user_id,
            user_ws_id=user_id,  # proxy: use user_id until per-connection IDs land
            agent_version="tether-agent-2.0",
            options=options,
            user_message=text,
            conversation_id=conversation_id,
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
    pool_client: Any = None,
) -> None:
    """Handle tether-agent-2.5: premium session for paid/admin users, 1.0 fallback for free.

    Paid users and admin users are routed to the premium handler (Session + Beacon + RAG).
    Admin users bypass the subscription check entirely — no subscription row required.
    Free users (non-admin, non-paid) receive an upgrade notice and fall back to tether-agent-1.0.
    If tether-premium is not installed, paid/admin users also fall back to 1.0.

    pool_client is the agent-pool-manager PoolClient.  When provided it is threaded through
    to the premium handler so PipelineBackend can acquire warm subprocesses instead of spawning
    inline.  When absent, it is created from config automatically so callers that don't have
    it on hand still get pool routing.

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
        # Resolve pool_client: use caller-supplied one, or create from config.
        # Mirror the LayerClient pattern in _dispatch_v2_0: construct lazily from
        # config rather than requiring callers to pass it explicitly.
        effective_pool_client = pool_client
        if effective_pool_client is None:
            try:
                from agent_pool_manager.client import from_config
                from config.loader import config as _cfg
                effective_pool_client = from_config(_cfg)
            except Exception:
                logger.warning(
                    "dispatch_v25: could not create pool_client from config for user_id=%s"
                    " — premium handler will run without pool routing",
                    user_id,
                    exc_info=True,
                )

        # Wrap send_fn so we can detect whether the premium handler streamed
        # any output before raising.  If it did, we must NOT run handle_message
        # (1.0 fallback) — doing so would splice a second response on top of
        # partial premium output the user has already received.
        tracked_send = _SendTracker(send_fn)
        try:
            from tether_premium.register import get_premium_handler
            from db.pg_queries import get_anchors
            from bot.handler_utils import get_current_anchor
            from bot.llm import _llm_env_extras, _llm_user_id

            async with pg.get_conn(pool, user_id) as conn:
                anchors = await get_anchors(conn)
            current_anchor = get_current_anchor(anchors)

            # Inner coroutine to call the handler — defined once and used in
            # both the vault-materialized and no-vault branches below.
            async def _invoke_handler() -> Any:
                return await get_premium_handler()(
                    text, pool, user_id, anchors, current_anchor,
                    send_fn=tracked_send, status_fn=status_fn,
                    pool_client=effective_pool_client,
                )

            # Set _llm_user_id contextvar so PipelineBackend._complete_via_pool() uses
            # the current request's user_id at call time, not the frozen one baked into
            # the singleton LLMRouter/PipelineBackend instance.  This is the fix for the
            # singleton user_id capture bug: without this, all requests after the first
            # would route pool handles to the first caller's user_id.
            uid_token = _llm_user_id.set(user_id)
            try:
                # Materialize vault credentials and set _llm_env_extras so every LLM
                # call inside the premium handler (PipelineBackend, AgentSDKBackend)
                # inherits the user's OAuth token via the subprocess env.
                # Pattern mirrors handle_message() in bot/message_handler.py.
                if vault is not None:
                    async with vault.with_lock(user_id):
                        # Sentinel flag: True once we have entered the vault.materialize
                        # context manager.  Used in except ValueError below to distinguish
                        # "no credentials stored" (flag=False, safe to call handler without
                        # vault) from "ValueError raised inside the handler itself" (flag=True,
                        # must re-raise — otherwise the handler is invoked a second time).
                        _vault_materialized = False
                        try:
                            async with vault.materialize(user_id) as env_extras:
                                _vault_materialized = True
                                token = _llm_env_extras.set(dict(env_extras))
                                try:
                                    response = await _invoke_handler()
                                finally:
                                    _llm_env_extras.reset(token)
                        except ValueError:
                            if _vault_materialized:
                                # ValueError came from inside the handler, not from
                                # vault.materialize().  Re-raise so the outer except
                                # Exception handler deals with it (and runs 1.0 fallback).
                                raise
                            # No credentials stored for this user — run without env injection.
                            logger.warning(
                                "dispatch_v25: no vault credentials for user_id=%s"
                                " — running premium handler without OAuth env",
                                user_id,
                            )
                            response = await _invoke_handler()
                else:
                    response = await _invoke_handler()
            finally:
                _llm_user_id.reset(uid_token)

            tracked_send(response or "")
            logger.info(
                "dispatch_v25: response delivered via tracked_send, chars=%d user_id=%s",
                len(response or ""),
                user_id,
            )
            return
        except (ImportError, NotImplementedError) as exc:
            # Log exc_info so the actual missing symbol or not-implemented site
            # appears in the log — without this, the error is silent and the
            # "premium not available" message is misleading (implies the package
            # is absent when it may be an import symbol mismatch inside the handler).
            logger.warning(
                "dispatch_v25: premium handler raised %s for user_id=%s"
                " — falling back to 1.0: %s",
                type(exc).__name__,
                user_id,
                exc,
                exc_info=True,
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
    conversation_id: str | None = None,
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
        conversation_id: Optional conversation this message belongs to. Forwarded
            to the 2.0 layer session so scope gating can resolve the conversation's
            context_node_id as scope_source_node_id. Not used by 1.0 or 2.5.
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
            conversation_id=conversation_id,
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
