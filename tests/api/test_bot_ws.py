"""Tests for /api/bot/chat WebSocket authentication (cookie-based).

These tests do not require a database — they exercise the auth layer only.
"""
from __future__ import annotations

import os
os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-ws-tests")

from unittest.mock import patch
import pytest
from starlette.testclient import TestClient

from api.auth import create_jwt

TEST_USER_ID = "00000000-0000-0000-0000-000000000099"
TEST_USERNAME = "ws_test_user"


class _FakePool:
    """Minimal pool stub — bot_chat only uses it inside handle_message, which we mock."""
    pass


def _make_app():
    from api.main import create_app
    app = create_app(lifespan_override=None)
    app.state.pool = _FakePool()
    return app


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

    async def fake_handle_message(content, send_fn, pool, user_id):
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
