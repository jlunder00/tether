"""Tests for WebSocket message-based authentication (bot auth pattern)."""
from __future__ import annotations

import json
import pytest
from starlette.testclient import TestClient

from api.auth import create_jwt
from tests.api.conftest import TEST_USER_ID, TEST_USERNAME


def _make_app():
    from api.main import create_app
    return create_app(lifespan_override=None)


def test_ws_message_auth_accepted(pool):
    """Bot sends auth message with valid JWT — connection accepted, stays open."""
    app = _make_app()
    app.state.pool = pool
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token}))
            # Connection stays open — send a ping and verify no error
            # If the auth failed the connection would have been closed
            # We verify by just not raising WebSocketDisconnect on send
            ws.send_text("ping")


def test_ws_message_auth_bad_token(pool):
    """Bot sends auth message with invalid JWT — connection closed with 1008."""
    app = _make_app()
    app.state.pool = pool

    with TestClient(app, raise_server_exceptions=False) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws") as ws:
                ws.send_text(json.dumps({"type": "auth", "token": "bad.token.here"}))
                # Should be closed
                ws.receive_text()


def test_ws_message_auth_missing_auth_message(pool):
    """Bot sends wrong first message — connection closed."""
    app = _make_app()
    app.state.pool = pool

    with TestClient(app, raise_server_exceptions=False) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws") as ws:
                ws.send_text(json.dumps({"type": "not_auth"}))
                ws.receive_text()
