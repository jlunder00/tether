"""Tests for admin JWT WS channel — bot connects via message-auth and gets
registered under both its own user_id AND the special '__bot__' channel so it
can receive meeting events for any user.

These tests do NOT require a database — they exercise the auth and connection
registration layer only.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-admin-ws-tests")

from contextlib import asynccontextmanager

import pytest
from starlette.testclient import TestClient

from api.auth import create_jwt
from api.ws import ConnectionManager

# Use a UUID that does NOT collide with conftest.TEST_USER_ID (...0001)
BOT_USER_ID = "00000000-0000-0000-0000-000000000b07"
BOT_USERNAME = "bot"

REGULAR_USER_ID = "00000000-0000-0000-0000-000000000099"
REGULAR_USERNAME = "regular_user"


class _FakePool:
    """Minimal pool stub — WS auth does not hit the DB."""
    pass


@asynccontextmanager
async def _noop_lifespan(app):
    app.state.pool = _FakePool()
    yield


def _make_app():
    from api.main import create_app
    return create_app(lifespan_override=_noop_lifespan)


# ── ConnectionManager unit tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manager_broadcast_bot_channel_reaches_admin():
    """Broadcast to '__bot__' channel reaches a connected admin websocket."""
    manager = ConnectionManager()

    class MockWS:
        def __init__(self):
            self.sent = []
        async def accept(self): pass
        async def send_json(self, data):
            self.sent.append(data)

    ws = MockWS()
    await manager.connect(ws, "__bot__")
    await manager.broadcast({"type": "meeting_request", "request_id": 1}, "__bot__")
    assert ws.sent == [{"type": "meeting_request", "request_id": 1}]


@pytest.mark.asyncio
async def test_manager_register_under_two_keys():
    """A single WS can be registered under two separate user_id keys."""
    manager = ConnectionManager()

    class MockWS:
        def __init__(self):
            self.sent = []
        async def accept(self): pass
        async def send_json(self, data):
            self.sent.append(data)

    ws = MockWS()
    await manager.connect(ws, "user-abc")
    # Also register under __bot__ without a double-accept
    manager._connections.setdefault("__bot__", []).append(ws)

    await manager.broadcast({"type": "ping"}, "user-abc")
    await manager.broadcast({"type": "pong"}, "__bot__")
    assert ws.sent == [{"type": "ping"}, {"type": "pong"}]


# ── Integration tests — /ws endpoint ─────────────────────────────────────────

def test_admin_cookie_ws_registers_under_bot_channel():
    """Admin JWT via cookie registers WS under both user_id and __bot__."""
    app = _make_app()
    token = create_jwt(BOT_USER_ID, BOT_USERNAME, is_admin=True)

    from api.ws import manager as global_manager

    with TestClient(app, raise_server_exceptions=False) as client:
        with client.websocket_connect(
            "/ws",
            cookies={"tether_token": token},
        ) as ws:
            # Connection accepted — verify both keys registered
            assert BOT_USER_ID in global_manager._connections
            assert len(global_manager._connections[BOT_USER_ID]) == 1
            assert "__bot__" in global_manager._connections
            assert len(global_manager._connections["__bot__"]) == 1
            # Same websocket object registered under both keys
            assert (
                global_manager._connections[BOT_USER_ID][0]
                is global_manager._connections["__bot__"][0]
            )

    # After disconnect, both keys should be cleaned up
    assert global_manager._connections.get(BOT_USER_ID, []) == []
    assert global_manager._connections.get("__bot__", []) == []


def test_admin_message_auth_ws_registers_under_bot_channel():
    """Admin JWT via message-based auth registers WS under both user_id and __bot__."""
    app = _make_app()
    token = create_jwt(BOT_USER_ID, BOT_USERNAME, is_admin=True)

    from api.ws import manager as global_manager

    with TestClient(app, raise_server_exceptions=False) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token}))
            # Send a follow-up ping to confirm connection is alive
            ws.send_text("ping")

            assert BOT_USER_ID in global_manager._connections
            assert "__bot__" in global_manager._connections


def test_non_admin_cookie_ws_does_not_register_under_bot_channel():
    """Non-admin JWT via cookie does NOT get registered under __bot__."""
    app = _make_app()
    token = create_jwt(REGULAR_USER_ID, REGULAR_USERNAME, is_admin=False)

    from api.ws import manager as global_manager

    with TestClient(app, raise_server_exceptions=False) as client:
        with client.websocket_connect(
            "/ws",
            cookies={"tether_token": token},
        ) as ws:
            ws.send_text("ping")

            assert REGULAR_USER_ID in global_manager._connections
            # __bot__ should NOT be set for non-admin users
            assert global_manager._connections.get("__bot__", []) == []


def test_non_admin_message_auth_ws_does_not_register_under_bot_channel():
    """Non-admin JWT via message auth does NOT get registered under __bot__."""
    app = _make_app()
    token = create_jwt(REGULAR_USER_ID, REGULAR_USERNAME, is_admin=False)

    from api.ws import manager as global_manager

    with TestClient(app, raise_server_exceptions=False) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token}))
            ws.send_text("ping")

            assert REGULAR_USER_ID in global_manager._connections
            assert global_manager._connections.get("__bot__", []) == []
