"""Unified notification dispatcher for Tether bot.

Single entry point for all bot-initiated messages. Resolves or creates
the target conversation, files a conversation_history record, then
delivers the message to each configured channel.

Usage (Phase C and later — not called from existing code yet):

    from bot.notify import dispatch

    result = await dispatch(
        user_id=user_id,
        notification_type="anchor_ping",
        text="Good morning! Here's your morning plan...",
        pool=pool,
        priority="important",
        thread_key=f"anchor:{anchor_id}:{date.today()}",
        ws_manager=ws_manager,
    )
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import asyncpg

import db.postgres as pg
from db.pg_queries import conversations as conv_queries
from db.pg_queries import notifications as notif_queries

logger = logging.getLogger(__name__)

NotificationPriority = Literal["normal", "important", "urgent"]
NotificationChannel = Literal["telegram", "web", "discord", "slack"]


@dataclass
class NotificationResult:
    """Outcome of a dispatch() call."""

    conversation_id: str
    channels_sent: list[str] = field(default_factory=list)
    channels_failed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def dispatch(
    user_id: str,
    notification_type: str,
    text: str,
    pool,
    *,
    priority: NotificationPriority = "normal",
    context_node_id: str | None = None,
    thread_key: str | None = None,
    conversation_id: str | None = None,
    channels: list[str] | None = None,
    ws_manager=None,
) -> NotificationResult:
    """Route a notification to all configured channels for this user/type.

    Args:
        user_id: The recipient's UUID.
        notification_type: Logical type key used for routing lookup
            (e.g. "anchor_ping", "task_followup", "beacon", "bot_reply").
        text: The message text to deliver.
        pool: Async connection pool (asyncpg.Pool).
        priority: Urgency level — 'normal' | 'important' | 'urgent'.
        context_node_id: Optional context node to file the conversation under.
        thread_key: When set, uses thread_by_key routing to find/create the
            conversation. Ignored if conversation_id is provided.
        conversation_id: When provided, bypasses _resolve_conversation()
            entirely and files directly into this conversation. Used by
            Phase C call sites that already know the active conversation
            (e.g. bot replies in an ongoing interactive session).
        channels: Override the routing prefs. When provided, only these
            channel types are attempted (e.g. ["telegram"], ["web"]).
        ws_manager: ConnectionManager instance for web channel delivery.
            Required for 'web' channel; absent → web channel fails gracefully.

    Returns:
        NotificationResult with the resolved conversation_id and per-channel
        send outcomes.
    """
    async with pg.get_conn(pool, user_id) as conn:
        # ------------------------------------------------------------------
        # 1. Resolve the target conversation
        # ------------------------------------------------------------------
        if conversation_id is None:
            routing = await notif_queries.get_notification_routing_with_defaults(
                conn, user_id
            )
            conversation_id = await _resolve_conversation(
                conn=conn,
                user_id=user_id,
                notification_type=notification_type,
                routing=routing,
                context_node_id=context_node_id,
                thread_key=thread_key,
            )

        # ------------------------------------------------------------------
        # 2. File message to conversation_history with new columns
        # ------------------------------------------------------------------
        channel_for_history = (channels[0] if channels else "web")
        await conn.execute(
            """
            INSERT INTO conversation_history (user_id, role, body, conversation_id, source, channel)
            VALUES ($1::uuid, 'assistant', $2, $3::uuid, 'notification', $4)
            """,
            user_id,
            text,
            conversation_id,
            channel_for_history,
        )

        await conv_queries.touch_conversation(conn, conversation_id)

        # ------------------------------------------------------------------
        # 3. Determine which channel types to send on
        # ------------------------------------------------------------------
        if channels is not None:
            target_channels = channels
        else:
            routing = await notif_queries.get_notification_routing_with_defaults(
                conn, user_id
            )
            type_routing = routing.get(notification_type, {})
            target_channels = type_routing.get("external", [])

        # ------------------------------------------------------------------
        # 4. Load channel configs and send
        # ------------------------------------------------------------------
        result = NotificationResult(conversation_id=conversation_id)

        for channel_type in target_channels:
            try:
                channel_rows = await notif_queries.get_channels_by_type(
                    conn, user_id, channel_type
                )

                if channel_type == "telegram":
                    if not channel_rows:
                        logger.debug(
                            "dispatch: no telegram channel configured for user %s", user_id
                        )
                        continue
                    for ch in channel_rows:
                        chat_id = ch["config"].get("chat_id", "")
                        await _send_telegram_channel(chat_id, text)
                    result.channels_sent.append("telegram")

                elif channel_type == "web":
                    if ws_manager is None:
                        logger.warning(
                            "dispatch: web channel requested but ws_manager is None"
                        )
                        result.channels_failed.append("web")
                        continue
                    await _send_web_channel(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        text=text,
                        priority=priority,
                        ws_manager=ws_manager,
                    )
                    result.channels_sent.append("web")

                elif channel_type == "discord":
                    if not channel_rows:
                        continue
                    for ch in channel_rows:
                        await _send_discord_channel(
                            ch["config"].get("webhook_url", ""), text
                        )
                    result.channels_sent.append("discord")

                elif channel_type == "slack":
                    if not channel_rows:
                        continue
                    for ch in channel_rows:
                        await _send_slack_channel(
                            ch["config"].get("webhook_url", ""), text
                        )
                    result.channels_sent.append("slack")

                else:
                    logger.warning("dispatch: unknown channel type %r — skipping", channel_type)

            except NotImplementedError:
                raise
            except Exception:
                logger.exception(
                    "dispatch: channel %r failed for user %s", channel_type, user_id
                )
                result.channels_failed.append(channel_type)

    return result


# ---------------------------------------------------------------------------
# Private: conversation resolution
# ---------------------------------------------------------------------------


async def _resolve_conversation(
    *,
    conn: asyncpg.Connection,
    user_id: str,
    notification_type: str,
    routing: dict,
    context_node_id: str | None,
    thread_key: str | None,
) -> str:
    """Find or create the target conversation. Returns conversation_id.

    Routing modes:
      thread_by_key — deduplicate by (user_id, thread_key)
      fixed         — use a pre-configured conversation_id from routing prefs
      bot_decides   — pick the most relevant open conversation (fallback: new)
      new_each      — always create a new conversation
    """
    type_routing = routing.get(notification_type, {})
    mode = type_routing.get("mode", "thread_by_key")
    conv_priority = type_routing.get("priority", "normal")

    if mode == "thread_by_key":
        key = thread_key or _build_thread_key(type_routing.get("key_template", ""), notification_type)
        name = _default_conv_name(notification_type)
        return await conv_queries.get_or_create_by_thread_key(
            conn,
            user_id=user_id,
            thread_key=key,
            name=name,
            notification_type=notification_type,
            context_node_id=context_node_id,
            priority=conv_priority,
        )

    elif mode == "fixed":
        fixed_id = type_routing.get("conversation_id")
        if fixed_id:
            return fixed_id
        # Fallback: create new
        logger.warning(
            "_resolve_conversation: fixed mode but no conversation_id in routing for %s",
            notification_type,
        )
        return await conv_queries.create_conversation(
            conn,
            user_id=user_id,
            name=_default_conv_name(notification_type),
            notification_type=notification_type,
            context_node_id=context_node_id,
            priority=conv_priority,
        )

    elif mode == "new_each":
        return await conv_queries.create_conversation(
            conn,
            user_id=user_id,
            name=_default_conv_name(notification_type),
            notification_type=notification_type,
            context_node_id=context_node_id,
            priority=conv_priority,
        )

    else:
        # bot_decides or unknown — create a new conversation for now.
        # Phase G will implement the "most relevant open conversation" logic.
        return await conv_queries.create_conversation(
            conn,
            user_id=user_id,
            name=_default_conv_name(notification_type),
            notification_type=notification_type,
            context_node_id=context_node_id,
            priority=conv_priority,
        )


def _build_thread_key(template: str, notification_type: str) -> str:
    """Build a thread key from a template. Falls back to notification_type if template empty."""
    if not template:
        return notification_type
    # Templates like "anchor:{anchor_id}:{date}" are filled by callers;
    # if they arrive here unfilled, return the template literal as the key.
    return template


def _default_conv_name(notification_type: str) -> str:
    _NAMES = {
        "anchor_ping": "Anchor Update",
        "task_followup": "Task Follow-up",
        "beacon": "Beacon Insight",
        "meeting_event": "Meeting",
        "scheduling_update": "Scheduling Update",
        "bot_reply": "Chat",
    }
    return _NAMES.get(notification_type, notification_type.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Private: channel senders
# ---------------------------------------------------------------------------


async def _send_telegram_channel(chat_id: str, text: str) -> None:
    """Send a message via the Telegram Bot API.

    Uses the python-telegram-bot library imported lazily to avoid making it a
    hard dependency when only web channel is in use.

    Phase C wires the actual bot token from config; for now the import and
    call structure is established here so tests can mock this function.
    """
    try:
        from telegram import Bot
        from bot.message_handler import _get_bot_token  # set up in Phase C
    except ImportError:
        logger.warning("_send_telegram_channel: python-telegram-bot not available")
        raise

    token = _get_bot_token()
    bot = Bot(token=token)
    await bot.send_message(chat_id=chat_id, text=text)


async def _send_web_channel(
    user_id: str,
    conversation_id: str,
    text: str,
    priority: NotificationPriority,
    ws_manager,
) -> None:
    """Push a notification event over WebSocket to the frontend."""
    await ws_manager.broadcast(
        {
            "type": "notification",
            "conversation_id": conversation_id,
            "text": text,
            "priority": priority,
            "ts": datetime.now(timezone.utc).isoformat(),
        },
        user_id,
    )


async def _send_discord_channel(webhook_url: str, text: str) -> None:
    """Discord channel — not yet implemented."""
    raise NotImplementedError("Discord channel not yet implemented")


async def _send_slack_channel(webhook_url: str, text: str) -> None:
    """Slack channel — not yet implemented."""
    raise NotImplementedError("Slack channel not yet implemented")
