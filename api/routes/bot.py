import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, WebSocket, WebSocketDisconnect
import asyncpg
from db.pg_queries import get_last_bot_activity
from db.pool_middleware import get_db_conn
from api.auth import auth_dependency, ws_auth_dependency
from bot.agent_dispatch import dispatch_message
from bot.message_handler import handle_message

router = APIRouter()
logger = logging.getLogger(__name__)


async def _cancel_and_wait(task: asyncio.Task, timeout: float = 5.0) -> None:
    """Cancel a task and wait for it to finish (best-effort, no raise).

    asyncio.Task.cancel() only schedules cancellation; the task keeps
    running until its next await point absorbs the CancelledError.  Always
    await after cancelling to avoid orphaned coroutines.
    """
    if task.done():
        return
    task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    except Exception as e:
        logger.debug("_cancel_and_wait: task raised during cancel: %s", e)


@router.get("/bot/health")
async def bot_health(_auth=Depends(auth_dependency),
                     conn: asyncpg.Connection = Depends(get_db_conn)):
    activity = await get_last_bot_activity(conn)
    if not activity:
        return {"status": "unknown", "last_activity": None}
    from datetime import datetime, timezone
    try:
        ts = datetime.fromisoformat(activity["ts"])
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except (ValueError, TypeError) as e:
        logger.error("bot_health: malformed last_activity timestamp %r: %s",
                     activity.get("ts"), e)
        age_min = float("inf")
    status = "ok" if age_min < 5 else "stale" if age_min < 30 else "offline"
    return {"status": status, "last_activity": activity}


async def _resolve_user_from_webhook_header(request: Request, pool) -> str | None:
    """Look up user_id from the X-Telegram-Bot-Api-Secret-Token header.

    Uses hmac.compare_digest for the empty-secret guard (constant time).
    Returns the user_id string if the secret resolves to a known user, else None.
    This is a no-RLS auth-schema lookup (telegram_connections has no RLS).
    """
    import db.postgres as pg
    import db.pg_auth_queries as pg_auth_queries

    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not provided:
        return None

    async with pg.get_conn(pool) as conn:
        return await pg_auth_queries.get_user_by_webhook_secret(conn, provided)


async def _process_telegram_update(
    update: dict,
    user_id: str,
    pool,
    vault,
) -> None:
    """Process a single Telegram Update dict for a known user.

    Called as a BackgroundTask after the webhook endpoint resolves the user from
    the X-Telegram-Bot-Api-Secret-Token header.

    Non-message updates (edited_message, channel_post, etc.) are silently ignored.

    First-message capture: if the user's telegram_chat_id is NULL, store
    update.message.chat.id and reply "Connected to Tether." — no further
    processing (the linking IS the action). Subsequent messages go to
    handle_message() as normal.
    """
    from bot.message_handler import _send_telegram
    import db.postgres as pg
    import db.pg_auth_queries as pg_auth_queries

    msg = update.get("message")
    if not msg:
        logger.debug("_process_telegram_update: no message field in update, skipping")
        return

    text = msg.get("text", "").strip()
    if not text:
        logger.debug("_process_telegram_update: empty text in message, skipping")
        return

    incoming_chat_id = str(msg.get("chat", {}).get("id", ""))
    if not incoming_chat_id:
        logger.warning("_process_telegram_update: no chat.id in update")
        return

    # Resolve per-user bot token for outbound messages.
    # Falls back to None if not set — handle_message handles its own fallbacks.
    fernet = getattr(vault, "_fernet", None) if vault else None
    token: str | None = None
    if fernet is not None:
        try:
            async with pg.get_conn(pool) as conn:
                token = await pg_auth_queries.get_bot_token(conn, user_id, fernet)
        except Exception as exc:
            logger.warning(
                "_process_telegram_update: could not fetch per-user bot token: %s", exc
            )

    if not token:
        from config.loader import config as tether_config
        token = tether_config.get("telegram.bot_token", "")

    send_fn = lambda m, cid=incoming_chat_id: _send_telegram(token, cid, m)

    # First-message capture: when telegram_chat_id is NULL, store it and
    # reply "Connected to Tether." — simplified linking per Jason's override.
    # No /link slash command, no 6-digit code needed.
    try:
        async with pg.get_conn(pool) as conn:
            current_chat_id = await pg_auth_queries.get_telegram_chat_id(conn, user_id)
    except Exception as exc:
        logger.error(
            "_process_telegram_update: get_telegram_chat_id failed user_id=%s: %s",
            user_id, exc, exc_info=True,
        )
        return

    if current_chat_id is None:
        # First message — bind this chat_id to the user.
        try:
            async with pg.get_conn(pool) as conn:
                await pg_auth_queries.auto_link_chat_id(conn, user_id, incoming_chat_id)
            send_fn("Connected to Tether.")
            logger.info(
                "_process_telegram_update: first-message chat_id capture user_id=%s chat_id=%s",
                user_id, incoming_chat_id,
            )
        except Exception as exc:
            logger.error(
                "_process_telegram_update: chat_id capture failed user_id=%s: %s",
                user_id, exc, exc_info=True,
            )
        return

    try:
        await handle_message(text, send_fn=send_fn, pool=pool, user_id=user_id, vault=vault)
    except Exception as exc:
        logger.error("_process_telegram_update: handle_message raised: %s", exc, exc_info=True)
        try:
            send_fn(f"[Tether error: {exc}]")
        except Exception:
            pass


@router.post("/bot/telegram-webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """Receive Telegram Update payloads (webhook mode).

    Always responds 200 immediately — Telegram retries on non-200, so we must
    never return an error status. Unknown/missing secrets are silently discarded.

    Auth: X-Telegram-Bot-Api-Secret-Token header is used to resolve the user.
    Lookup: SELECT user_id FROM telegram_connections WHERE webhook_secret = $1
    (no-RLS auth-schema query). Processing happens in a BackgroundTask.
    """
    pool = request.app.state.pool
    vault = getattr(request.app.state, "vault", None)

    user_id = await _resolve_user_from_webhook_header(request, pool)
    if user_id is None:
        # Unknown or missing secret — discard silently.
        return Response(status_code=200)

    update = await request.json()
    background_tasks.add_task(_process_telegram_update, update, user_id, pool, vault)
    return Response(status_code=200)


@router.websocket("/bot/chat")
async def bot_chat(websocket: WebSocket,
                   _auth=Depends(ws_auth_dependency)):
    """WebSocket handler for bot chat.

    Design (per spec §3.3 + §4.2):
    - Each user message starts a session_task running handle_message.
    - A parallel recv_task listens for the next client message concurrently.
    - asyncio.wait(FIRST_COMPLETED) races them so {"type": "stop"} can
      interrupt the session mid-run.
    - status_fn: async callback passed to handle_message that pushes
      {"type": "status"} frames immediately — no accumulation.
    - Session errors send {"type": "error"} + {"type": "done"} without
      closing the connection; the client can send another message.
      TimeoutError gets a user-friendly message explaining state is preserved.
    - WebSocketDisconnect (client gone) cancels the running session_task
      and awaits it before returning (prevents orphaned LLM calls).

    """
    await websocket.accept()
    pool = websocket.app.state.pool
    user_id = websocket.state.user_id
    logger.info("bot_chat: connection accepted, user_id=%s", user_id)

    session_task: asyncio.Task | None = None

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            logger.info("bot_chat: received message type=%s", msg_type)

            if msg_type == "stop":
                # Idle stop — no session is running, silently ignore.
                logger.debug("bot_chat: idle stop received, ignoring")
                continue

            content = data.get("content")
            if not content:
                logger.warning("bot_chat: message missing content, user_id=%s", user_id)
                await websocket.send_json({"type": "error", "message": "Missing content"})
                continue

            # M2: read agent_version and dispatch to the correct pipeline.
            # 1.0 → existing JSON-mutation pipeline; 2.0/2.5 → stub + 1.0 fallback.
            # Unknown or missing versions default to tether-agent-2.0 (picker default).
            agent_version = data.get("agent_version") or "tether-agent-2.0"
            logger.info("bot_chat: agent_version=%s user_id=%s", agent_version, user_id)

            # Async status callback: called by the premium session's
            # send_status_update tool to push real-time progress frames.
            # If the WebSocket has gone away, log and re-raise so the session
            # task surfaces a disconnect rather than a confusing "Session error".
            async def status_fn(msg: str) -> None:
                try:
                    await websocket.send_json({"type": "status", "content": msg})
                except Exception as e:
                    logger.debug(
                        "bot_chat: status_fn send failed (client likely disconnected),"
                        " user_id=%s: %s",
                        user_id, e,
                    )
                    raise  # Let the session task propagate disconnect to the outer handler

            # Async event callback for streamed layer events (text deltas,
            # permission requests, etc.). agent_text_delta events are sent
            # as agent_text_delta frames so the browser can render them
            # incrementally. Other event types (including turn_complete) are
            # forwarded as-is.
            # turn_complete_sent tracks whether event_fn already forwarded a
            # turn_complete from the session — if so, the response_parts path
            # below skips its own turn_complete to prevent a double-send that
            # would poison the frontend's incoming queue for the next message.
            turn_complete_sent: list[bool] = [False]

            async def event_fn(event: dict) -> None:
                try:
                    etype = event.get("type")
                    if etype == "agent_text_delta":
                        delta = event.get("delta", "")
                        if delta:
                            await websocket.send_json({"type": "agent_text_delta", "delta": delta})
                    else:
                        if etype == "turn_complete":
                            turn_complete_sent[0] = True
                        await websocket.send_json(event)
                except Exception as e:
                    logger.debug(
                        "bot_chat: event_fn send failed (client likely disconnected),"
                        " user_id=%s: %s",
                        user_id, e,
                    )
                    raise

            # Capture responses delivered via send_fn. handle_message always
            # calls send_fn(final) and returns None — the return value is not
            # used for response delivery. This list is local to each message
            # so it resets automatically on the next loop iteration.
            response_parts: list[str] = []

            def capture_send_fn(msg: str) -> None:
                response_parts.append(msg)

            # Run the session as a task so we can race it against an incoming
            # stop message without blocking the event loop.
            session_task = asyncio.create_task(
                dispatch_message(
                    agent_version,
                    content,
                    send_fn=capture_send_fn,
                    pool=pool,
                    user_id=user_id,
                    vault=getattr(websocket.app.state, "vault", None),
                    status_fn=status_fn,
                    event_fn=event_fn,
                    is_admin=websocket.state.is_admin,
                )
            )

            # Race session completion against the next incoming client message.
            recv_task = asyncio.create_task(websocket.receive_json())
            done, _pending = await asyncio.wait(
                {session_task, recv_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # --- recv_task won (client sent something mid-session) ---
            if recv_task in done and session_task not in done:
                try:
                    incoming = recv_task.result()
                except Exception as exc:
                    # WebSocketDisconnect or protocol error: cancel session (awaited)
                    # and propagate to the outer except WebSocketDisconnect handler.
                    await _cancel_and_wait(session_task)
                    raise exc

                if incoming.get("type") == "stop":
                    # Await cancellation before sending "Stopped." to guarantee no
                    # further status frames from the session arrive after the ack.
                    await _cancel_and_wait(session_task)
                    await websocket.send_json({"type": "status", "content": "Stopped."})
                    await websocket.send_json({"type": "turn_complete", "final_text": "", "session_id": ""})
                    session_task = None
                    continue  # Back to outer loop — ready for next message

                # Non-stop message mid-session (UI race / protocol error):
                # drop it, let the session finish. recv_task is done (no orphan).
                logger.warning(
                    "bot_chat: mid-session message type=%r dropped (session continues),"
                    " user_id=%s",
                    incoming.get("type"), user_id,
                )
                # Fall through to await session_task, with recv_task cleanup in finally.

            # --- session_task won (or fell through from non-stop mid-session case) ---
            # Await session if not yet done; always clean up recv_task.
            try:
                if not session_task.done():
                    await session_task
            finally:
                # Cancel and clean up recv_task in all cases (normal, exception, cancel).
                if not recv_task.done():
                    recv_task.cancel()
                    try:
                        await recv_task
                    except asyncio.CancelledError:
                        pass
                    except WebSocketDisconnect:
                        # Client disconnected while awaiting session: propagate so
                        # the outer handler can cancel session_task and return cleanly.
                        raise
                    except Exception as e:
                        logger.warning(
                            "bot_chat: unexpected error awaiting cancelled recv_task,"
                            " user_id=%s: %s",
                            user_id, e, exc_info=True,
                        )

            if session_task is None or session_task.cancelled():
                continue

            # Re-raise any exception from handle_message so error handlers below
            # can send a user-facing error frame and keep the connection alive.
            try:
                session_task.result()  # returns None; raises if handle_message raised
            except TimeoutError:
                # Session exceeded its per-intent timeout. The session manager has
                # already closed the session on its end; state is preserved and the
                # user can send another message to start a fresh session.
                logger.warning("bot_chat: session timed out user_id=%s", user_id)
                await websocket.send_json({
                    "type": "error",
                    "message": (
                        "Session timed out — your state is saved, "
                        "send another message to continue."
                    ),
                })
                await websocket.send_json({"type": "turn_complete", "final_text": "", "session_id": ""})
                session_task = None
                continue
            except Exception as e:
                logger.error(
                    "bot_chat: session raised for user_id=%s: %s",
                    user_id, e, exc_info=True,
                )
                await websocket.send_json({
                    "type": "error",
                    "message": "Something went wrong. Please try again.",
                })
                await websocket.send_json({"type": "turn_complete", "final_text": "", "session_id": ""})
                session_task = None
                continue

            session_task = None
            if not turn_complete_sent[0]:
                response = "\n\n".join(response_parts) if response_parts else ""
                await websocket.send_json({"type": "turn_complete", "final_text": response, "session_id": ""})

    except WebSocketDisconnect:
        await _cancel_and_wait(session_task) if session_task else None
        return
    except Exception as e:
        logger.error("bot_chat: unhandled exception user_id=%s: %s", user_id, e, exc_info=True)
        await _cancel_and_wait(session_task) if session_task else None
        try:
            await websocket.send_json({"type": "error", "message": "Internal error"})
        except Exception:
            pass
        raise
