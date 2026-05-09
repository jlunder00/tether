"""Tests for server-side WebSocket topic filtering for bot connections.

Bot connections register with a delegation set (user_ids they are authorized
to receive events for). Server-side filtering ensures bots only receive events
for delegated users.

These tests do NOT require a database — unit tests exercise ConnectionManager
directly. One integration test uses monkeypatching for the delegation lookup.
"""
from __future__ import annotations

import os

os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-ws-filtering-tests")

from contextlib import asynccontextmanager

import pytest
from starlette.testclient import TestClient

from api.auth import create_jwt
from api.ws import ConnectionManager


USER_A_ID = "00000000-0000-0000-0000-aaaaaaaaaaaa"
USER_B_ID = "00000000-0000-0000-0000-bbbbbbbbbbbb"
BOT_ID = "00000000-0000-0000-0000-000000000b07"
BOT_USERNAME = "bot_service"


class _MockWS:
    """Minimal mock WebSocket — captures sent messages."""

    def __init__(self):
        self.sent: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class _FakePool:
    """Stub pool — WS auth does not hit the DB."""
    pass


@asynccontextmanager
async def _noop_lifespan(app):
    app.state.pool = _FakePool()
    yield


def _make_app():
    from api.main import create_app
    return create_app(lifespan_override=_noop_lifespan)


# ── ConnectionManager unit tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bot_receives_event_for_delegated_user():
    """Bot with delegation for user A receives events broadcast to user A."""
    manager = ConnectionManager()
    bot_ws = _MockWS()
    manager.register_bot(bot_ws, BOT_ID, {USER_A_ID})

    await manager.broadcast({"type": "task_updated", "id": "t1"}, USER_A_ID)

    assert len(bot_ws.sent) == 1
    assert bot_ws.sent[0]["type"] == "task_updated"
    assert bot_ws.sent[0]["for_user_id"] == USER_A_ID


@pytest.mark.asyncio
async def test_bot_does_not_receive_event_for_non_delegated_user():
    """Bot with delegation for user A does NOT receive events broadcast to user B."""
    manager = ConnectionManager()
    bot_ws = _MockWS()
    manager.register_bot(bot_ws, BOT_ID, {USER_A_ID})

    await manager.broadcast({"type": "task_updated", "id": "t2"}, USER_B_ID)

    assert bot_ws.sent == []


@pytest.mark.asyncio
async def test_bot_receives_events_for_all_delegated_users():
    """Bot with delegation for both A and B receives events for both."""
    manager = ConnectionManager()
    bot_ws = _MockWS()
    manager.register_bot(bot_ws, BOT_ID, {USER_A_ID, USER_B_ID})

    await manager.broadcast({"type": "anchor_updated"}, USER_A_ID)
    await manager.broadcast({"type": "anchor_updated"}, USER_B_ID)

    assert len(bot_ws.sent) == 2
    user_ids_received = {msg["for_user_id"] for msg in bot_ws.sent}
    assert user_ids_received == {USER_A_ID, USER_B_ID}


@pytest.mark.asyncio
async def test_update_bot_delegation_adds_new_user():
    """Adding a user to the delegation set causes bot to receive their events (no reconnect)."""
    manager = ConnectionManager()
    bot_ws = _MockWS()
    manager.register_bot(bot_ws, BOT_ID, {USER_A_ID})

    # Before update — user B's events not delivered
    await manager.broadcast({"type": "task_updated"}, USER_B_ID)
    assert bot_ws.sent == []

    # Expand delegation to include user B
    manager.update_bot_delegation(BOT_ID, {USER_A_ID, USER_B_ID})

    # After update — user B's events now delivered
    await manager.broadcast({"type": "task_updated"}, USER_B_ID)
    assert len(bot_ws.sent) == 1
    assert bot_ws.sent[0]["for_user_id"] == USER_B_ID


@pytest.mark.asyncio
async def test_revoke_delegation_stops_events_for_user():
    """Removing a user from the delegation set stops delivery of their events."""
    manager = ConnectionManager()
    bot_ws = _MockWS()
    manager.register_bot(bot_ws, BOT_ID, {USER_A_ID, USER_B_ID})

    # Confirm user A's events arrive before revocation
    await manager.broadcast({"type": "task_updated"}, USER_A_ID)
    assert len(bot_ws.sent) == 1

    # Revoke user A — only user B remains
    manager.update_bot_delegation(BOT_ID, {USER_B_ID})

    # User A's events no longer delivered
    await manager.broadcast({"type": "task_updated"}, USER_A_ID)
    assert len(bot_ws.sent) == 1  # count unchanged


@pytest.mark.asyncio
async def test_regular_user_broadcast_unaffected_by_bot_registration():
    """Regular user still receives their own events; undelegated bot receives none."""
    manager = ConnectionManager()
    user_ws = _MockWS()
    bot_ws = _MockWS()

    await manager.connect(user_ws, USER_A_ID)
    # Bot is NOT delegated for user A
    manager.register_bot(bot_ws, BOT_ID, {USER_B_ID})

    await manager.broadcast({"type": "plan_updated"}, USER_A_ID)

    assert user_ws.sent == [{"type": "plan_updated"}]
    assert bot_ws.sent == []


@pytest.mark.asyncio
async def test_bot_disconnect_removes_registration():
    """After disconnect_bot, no events are delivered to that connection."""
    manager = ConnectionManager()
    bot_ws = _MockWS()
    manager.register_bot(bot_ws, BOT_ID, {USER_A_ID})

    manager.disconnect_bot(BOT_ID)

    await manager.broadcast({"type": "task_updated"}, USER_A_ID)
    assert bot_ws.sent == []


# ── Integration test — /ws endpoint with is_bot_service JWT ─────────────────


def test_bot_service_ws_registers_with_delegation(monkeypatch):
    """Bot WS with is_bot_service=True JWT registers in _bot_connections with delegation set."""
    import db.pg_queries.api_keys as _api_keys

    async def _mock_get_delegated(pool, bot_service_id: str) -> set[str]:
        return {USER_A_ID}

    monkeypatch.setattr(_api_keys, "get_delegated_user_ids", _mock_get_delegated)

    app = _make_app()
    token = create_jwt(BOT_ID, BOT_USERNAME, is_admin=False, is_bot_service=True)

    from api.ws import manager as global_manager

    with TestClient(app, raise_server_exceptions=False) as client:
        with client.websocket_connect("/ws", cookies={"tether_token": token}) as ws:
            ws.send_text("ping")
            assert BOT_ID in global_manager._bot_connections
            _, delegated = global_manager._bot_connections[BOT_ID]
            assert USER_A_ID in delegated

    # After disconnect, bot registration is cleaned up
    assert BOT_ID not in global_manager._bot_connections
