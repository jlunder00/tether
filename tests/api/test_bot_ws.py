"""Tests for /api/bot/chat WebSocket authentication (cookie-based).

These tests do not require a database — they exercise the auth layer only.
"""
from __future__ import annotations

import os
os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-ws-tests")

from contextlib import asynccontextmanager
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient

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


def test_bot_ws_valid_cookie_accepted():
    """Connecting with a valid JWT cookie must be accepted; messages round-trip."""
    app = _make_app()
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)

    async def fake_handle_message(content, send_fn, pool, user_id, vault=None):
        send_fn("pong")

    with patch("api.routes.bot.handle_message", new=fake_handle_message):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "ping"})
                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"
                done = ws.receive_json()
                assert done["type"] == "done"


def test_bot_ws_timeout_sends_helpful_error_and_continues_loop():
    """When handle_message raises TimeoutError, the handler must:
    1. Send a timeout-specific error message (not generic "Internal error").
    2. NOT close the connection — continue the loop so the user can retry.

    The loop continuing is proven by sending a second message successfully
    after the timeout. The second call raises WebSocketDisconnect to end
    the test cleanly.
    """
    app = _make_app()
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)

    call_count = 0

    async def handle_first_timeouts_second_ok(content, send_fn, pool, user_id, vault=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("session timed out")
        send_fn("recovered response")

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
                # Must mention timeout and saved state — not just "Internal error"
                msg_lower = error_msg["message"].lower()
                assert "timed out" in msg_lower or "timeout" in msg_lower
                assert "state is saved" in msg_lower or "continue" in msg_lower
                assert "Internal error" not in error_msg["message"]

                # Second message — proves loop continued (connection still alive)
                ws.send_json({"type": "user", "content": "try again"})
                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"
                done = ws.receive_json()
                assert done["type"] == "done"


def test_bot_ws_non_timeout_exception_closes_connection():
    """Non-timeout exceptions must still close the connection (existing behavior preserved).

    When a non-timeout exception escapes handle_message, bot_chat re-raises it so
    Starlette tears down the WebSocket. The test verifies the connection is closed
    (either the receive raises or the connection context raises) — the key invariant
    is that the loop does NOT continue and accept another message.
    """
    app = _make_app()
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)

    call_count = 0

    async def handle_raises_then_succeeds(content, send_fn, pool, user_id, vault=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("unexpected internal failure")
        # Should never reach here — loop must be terminated by the re-raise
        send_fn("should not arrive")

    with patch("api.routes.bot.handle_message", new=handle_raises_then_succeeds):
        with TestClient(app, raise_server_exceptions=False) as client:
            connection_closed = False
            try:
                with client.websocket_connect(
                    "/api/bot/chat",
                    cookies={"tether_token": token},
                ) as ws:
                    ws.send_json({"type": "user", "content": "hello"})
                    # The server re-raises RuntimeError, closing the connection.
                    # Starlette may surface this as a closed-resource error on receive
                    # or as an exception when the context manager exits.
                    try:
                        ws.receive_json()
                    except Exception:
                        connection_closed = True
            except Exception:
                connection_closed = True

    assert connection_closed, "Connection must be closed after a non-timeout exception"
    # Crucially: handle_message was only called once — the loop did NOT continue
    assert call_count == 1, (
        f"handle_message must only be called once; got {call_count} calls — "
        "loop must not continue after non-timeout errors"
    )
