"""Tests for /api/bot/chat WebSocket handler.

Tests cover:
- Auth layer (cookie validation)
- Status message immediate push
- Parallel stop signal handling (asyncio.wait race)
- Timeout error — user-friendly message, connection kept alive
- Session error recovery — error+done frame, connection stays open
- WebSocket disconnect cleanup
"""
from __future__ import annotations

import asyncio
import os
import threading
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-ws-tests")

from api.auth import create_jwt

TEST_USER_ID = "00000000-0000-0000-0000-000000000099"
TEST_USERNAME = "ws_test_user"


class _FakePool:
    """Minimal pool stub — bot_chat only uses it inside handle_message, which we mock."""
    pass


@asynccontextmanager
async def _noop_lifespan(app):
    app.state.pool = _FakePool()
    app.state.vault = None  # vault not needed for these WS tests
    yield


def _make_app():
    from api.main import create_app
    return create_app(lifespan_override=_noop_lifespan)


def _valid_token():
    return create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

def test_bot_ws_no_cookie_rejected_1008():
    """Connecting to /api/bot/chat without a cookie must be rejected with 1008."""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/api/bot/chat") as ws:
                ws.receive_text()


def test_bot_ws_invalid_token_rejected_1008():
    """Connecting with an invalid JWT cookie must be rejected with 1008."""
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": "invalid.jwt.token"},
            ) as ws:
                ws.receive_text()


# ---------------------------------------------------------------------------
# Basic round-trip (redesigned handler: handle_message returns str|None)
# ---------------------------------------------------------------------------

def test_bot_ws_valid_cookie_accepted():
    """A valid JWT allows connection; a user message produces chunk + done.

    The redesigned handler uses handle_message's *return value* as the chunk
    content — send_fn is a no-op on WebSocket.  The mock must return a string.
    """
    app = _make_app()
    token = _valid_token()

    async def fake_handle_message(content, send_fn, pool, user_id, vault=None, status_fn=None):
        return "pong"

    with patch("api.routes.bot.handle_message", new=fake_handle_message):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "ping"})
                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"
                assert chunk["content"] == "pong"
                done = ws.receive_json()
                assert done["type"] == "done"


def test_bot_ws_none_response_skips_chunk():
    """When handle_message returns None, no chunk frame is sent — just done."""
    app = _make_app()
    token = _valid_token()

    async def fake_handle_message(content, send_fn, pool, user_id, vault=None, status_fn=None):
        return None

    with patch("api.routes.bot.handle_message", new=fake_handle_message):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "hello"})
                done = ws.receive_json()
                assert done["type"] == "done"


# ---------------------------------------------------------------------------
# Status messages — pushed immediately, not accumulated
# ---------------------------------------------------------------------------

def test_status_messages_pushed_immediately():
    """status_fn pushes a status frame before the session completes.

    The test verifies that the client receives:
      1. {"type": "status", "content": "Working on it..."}
      2. {"type": "chunk", "content": "final answer"}
      3. {"type": "done"}
    in that order — confirming real-time push rather than accumulation.
    """
    app = _make_app()
    token = _valid_token()

    async def fake_handle_with_status(content, send_fn, pool, user_id, vault=None, status_fn=None):
        if status_fn is not None:
            await status_fn("Working on it...")
        return "final answer"

    with patch("api.routes.bot.handle_message", new=fake_handle_with_status):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "plan my day"})

                status = ws.receive_json()
                assert status["type"] == "status"
                assert status["content"] == "Working on it..."

                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"
                assert chunk["content"] == "final answer"

                done = ws.receive_json()
                assert done["type"] == "done"


def test_multiple_status_messages_in_order():
    """Multiple status_fn calls are delivered in emission order."""
    app = _make_app()
    token = _valid_token()

    async def fake_handle_multi_status(content, send_fn, pool, user_id, vault=None, status_fn=None):
        if status_fn is not None:
            await status_fn("Step 1: Reading tasks")
            await status_fn("Step 2: Rescheduling blocks")
        return "done planning"

    with patch("api.routes.bot.handle_message", new=fake_handle_multi_status):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "plan"})

                s1 = ws.receive_json()
                assert s1 == {"type": "status", "content": "Step 1: Reading tasks"}

                s2 = ws.receive_json()
                assert s2 == {"type": "status", "content": "Step 2: Rescheduling blocks"}

                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"

                done = ws.receive_json()
                assert done["type"] == "done"


# ---------------------------------------------------------------------------
# Stop signal — parallel recv_task race
# ---------------------------------------------------------------------------

def test_stop_message_cancels_session():
    """Sending {"type": "stop"} while a session is running cancels it.

    The mock holds on an asyncio.sleep so the session never completes on its
    own.  The test sends stop immediately after the user message; the handler
    must cancel the session_task and reply with status("Stopped.") + done.
    """
    app = _make_app()
    token = _valid_token()

    # session_cancelled is set when the mock's CancelledError fires.
    session_cancelled = threading.Event()

    async def fake_long_session(content, send_fn, pool, user_id, vault=None, status_fn=None):
        try:
            await asyncio.sleep(30)  # Long enough that stop fires first
        except asyncio.CancelledError:
            session_cancelled.set()
            raise
        return "this should never arrive"

    with patch("api.routes.bot.handle_message", new=fake_long_session):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "plan my week"})
                ws.send_json({"type": "stop"})

                status = ws.receive_json()
                assert status["type"] == "status"
                assert status["content"] == "Stopped."

                done = ws.receive_json()
                assert done["type"] == "done"

    # Give the background task a moment to propagate CancelledError
    session_cancelled.wait(timeout=3)
    assert session_cancelled.is_set(), "session_task was not cancelled on stop"


def test_idle_stop_ignored():
    """A stop message when no session is running must be silently ignored."""
    app = _make_app()
    token = _valid_token()

    async def fake_handle_message(content, send_fn, pool, user_id, vault=None, status_fn=None):
        return "ok"

    with patch("api.routes.bot.handle_message", new=fake_handle_message):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                # Send idle stop — handler must ignore it, loop must not crash
                ws.send_json({"type": "stop"})

                # Now send a real user message — should still work normally
                ws.send_json({"type": "user", "content": "hello"})
                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"
                done = ws.receive_json()
                assert done["type"] == "done"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_missing_content_sends_error_keeps_connection():
    """A user message without 'content' sends error frame but does NOT close the WS."""
    app = _make_app()
    token = _valid_token()

    async def fake_handle_message(content, send_fn, pool, user_id, vault=None, status_fn=None):
        return "ok"

    with patch("api.routes.bot.handle_message", new=fake_handle_message):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user"})  # missing content
                error = ws.receive_json()
                assert error["type"] == "error"
                assert "missing" in error["message"].lower() or "content" in error["message"].lower()

                # Connection must still be alive — can send another message
                ws.send_json({"type": "user", "content": "retry"})
                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"
                done = ws.receive_json()
                assert done["type"] == "done"


# ---------------------------------------------------------------------------
# Session error recovery — connection stays alive for all error types
# ---------------------------------------------------------------------------

def test_bot_ws_timeout_sends_helpful_error_and_continues_loop():
    """When handle_message raises TimeoutError, the handler must:
    1. Send a timeout-specific error message (not generic "Internal error").
    2. NOT close the connection — continue the loop so the user can retry.
    """
    app = _make_app()
    token = _valid_token()

    call_count = 0

    async def handle_first_timeouts_second_ok(content, send_fn, pool, user_id,
                                               vault=None, status_fn=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("session timed out")
        return "recovered response"

    with patch("api.routes.bot.handle_message", new=handle_first_timeouts_second_ok):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                # First message — triggers timeout
                ws.send_json({"type": "user", "content": "plan my week"})
                error_msg = ws.receive_json()
                assert error_msg["type"] == "error"
                msg_lower = error_msg["message"].lower()
                assert "timed out" in msg_lower or "timeout" in msg_lower
                assert "state is saved" in msg_lower or "continue" in msg_lower
                assert "Internal error" not in error_msg["message"]
                done = ws.receive_json()
                assert done["type"] == "done"

                # Second message — proves loop continued (connection still alive)
                ws.send_json({"type": "user", "content": "try again"})
                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"
                assert chunk["content"] == "recovered response"
                done2 = ws.receive_json()
                assert done2["type"] == "done"


def test_session_error_sends_error_keeps_connection():
    """If handle_message raises a non-timeout error, the WS receives error+done
    and stays open — the redesigned handler is resilient for all error types."""
    app = _make_app()
    token = _valid_token()

    call_count = 0

    async def fake_handle_that_raises(content, send_fn, pool, user_id, vault=None, status_fn=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated session failure")
        return "recovered"

    with patch("api.routes.bot.handle_message", new=fake_handle_that_raises):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "first message"})
                error = ws.receive_json()
                assert error["type"] == "error"
                done = ws.receive_json()
                assert done["type"] == "done"

                # Connection must still be alive — next message works
                ws.send_json({"type": "user", "content": "second message"})
                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"
                assert chunk["content"] == "recovered"
                done2 = ws.receive_json()
                assert done2["type"] == "done"


# ---------------------------------------------------------------------------
# Disconnect cleanup
# ---------------------------------------------------------------------------

def test_disconnect_cancels_session_task():
    """WebSocketDisconnect while a session is running must cancel session_task.

    We verify this by checking that the mock's CancelledError branch fires
    (session_cancelled is set) after the client disconnects.
    """
    app = _make_app()
    token = _valid_token()

    session_started = threading.Event()
    session_cancelled = threading.Event()

    async def fake_long_session(content, send_fn, pool, user_id, vault=None, status_fn=None):
        session_started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            session_cancelled.set()
            raise
        return "unreachable"

    with patch("api.routes.bot.handle_message", new=fake_long_session):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "plan my day"})
                # Wait until the session is running before disconnecting
                session_started.wait(timeout=3)
            # Exiting the `with ws` block closes the WebSocket

    session_cancelled.wait(timeout=3)
    assert session_cancelled.is_set(), "session_task was not cancelled on disconnect"
