"""Tests for the bot_chat WebSocket permission_response link (brief 1d).

Covers the keystone fix: {"type": "permission_response", request_id, decision}
frames sent by the client mid-session must reach the interactive-agent-layer's
/permission/{request_id}/respond endpoint (via LayerClient.respond_to_permission),
and the mid-session recv loop must be able to consume MULTIPLE such frames in
a single turn instead of dropping everything after the first non-stop frame.

LayerClient is faked at the api.routes.bot import site (not real HTTP) — the
real POST body / endpoint contract is covered by
tests/interactive_agent_layer/test_client.py::test_respond_to_permission_*.
This file verifies bot.py maps decision -> approve correctly and drives the
loop correctly.
"""
from __future__ import annotations

import asyncio
import os
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
    pass


@asynccontextmanager
async def _noop_lifespan(app):
    app.state.pool = _FakePool()
    app.state.vault = None
    yield


def _make_app():
    from api.main import create_app
    return create_app(lifespan_override=_noop_lifespan)


def _valid_token():
    return create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)


class _FakeLayerClient:
    """Records (base_url) at construction and (request_id, approve) per call.

    Tests register an asyncio.Event per request_id in `events` before the
    permission_response frame is sent; respond_to_permission sets it so the
    fake dispatch_message coroutine (which awaits that event) can resume —
    this proves the call genuinely came from the server-side WS handler
    processing the incoming frame, not test-side coordination.
    """

    instances: list = []
    events: dict = {}

    def __init__(self, base_url):
        self.base_url = base_url
        self.calls: list = []
        _FakeLayerClient.instances.append(self)

    async def respond_to_permission(self, request_id, approve):
        self.calls.append((request_id, approve))
        ev = _FakeLayerClient.events.get(request_id)
        if ev is not None:
            ev.set()


class _RaisingLayerClient:
    """Simulates the layer being unreachable — respond_to_permission always raises."""

    def __init__(self, base_url):
        pass

    async def respond_to_permission(self, request_id, approve):
        raise RuntimeError("layer unreachable")


def setup_function(_fn):
    _FakeLayerClient.instances = []
    _FakeLayerClient.events = {}


def test_permission_response_forwards_to_layer_and_resumes_session():
    """A single permission_request/permission_response round trip:

    dispatch_message emits permission_request via event_fn, blocks until the
    approval lands, then completes the turn. bot_chat must forward the
    permission_response frame to the layer (via LayerClient) instead of
    dropping it, letting the session proceed.
    """
    app = _make_app()
    token = _valid_token()
    approved = asyncio.Event()
    _FakeLayerClient.events["req-1"] = approved

    async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
        event_fn = kwargs["event_fn"]
        await event_fn({
            "type": "permission_request",
            "request_id": "req-1",
            "kind": "user_action",
            "target": "delete_tasks",
            "session_id": "s1",
            "reason_from_bot": None,
        })
        await asyncio.wait_for(approved.wait(), timeout=5)
        send_fn("proceeded after approval")

    with patch("api.routes.bot.dispatch_message", new=fake_dispatch), \
         patch("api.routes.bot.LayerClient", new=_FakeLayerClient):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({
                    "type": "user", "content": "do something",
                    "agent_version": "tether-agent-2.0",
                })

                perm = ws.receive_json()
                assert perm["type"] == "permission_request"
                assert perm["request_id"] == "req-1"

                ws.send_json({
                    "type": "permission_response",
                    "request_id": "req-1",
                    "decision": "approve",
                })
                # Give the server-side handler a beat to invoke the fake layer
                # client and set the event before we assert on it below.

                tc = ws.receive_json()
                assert tc["type"] == "turn_complete"
                assert tc["final_text"] == "proceeded after approval"

    assert len(_FakeLayerClient.instances) >= 1
    all_calls = [c for inst in _FakeLayerClient.instances for c in inst.calls]
    assert ("req-1", True) in all_calls


def test_permission_response_deny_maps_to_approve_false():
    app = _make_app()
    token = _valid_token()
    approved = asyncio.Event()
    _FakeLayerClient.events["req-deny"] = approved

    async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
        event_fn = kwargs["event_fn"]
        await event_fn({
            "type": "permission_request",
            "request_id": "req-deny",
            "kind": "destructive",
            "target": "delete_context",
            "session_id": "s1",
            "reason_from_bot": None,
        })
        await asyncio.wait_for(approved.wait(), timeout=5)
        send_fn("handled denial")

    with patch("api.routes.bot.dispatch_message", new=fake_dispatch), \
         patch("api.routes.bot.LayerClient", new=_FakeLayerClient):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({
                    "type": "user", "content": "do something risky",
                    "agent_version": "tether-agent-2.0",
                })
                perm = ws.receive_json()
                assert perm["request_id"] == "req-deny"

                ws.send_json({
                    "type": "permission_response",
                    "request_id": "req-deny",
                    "decision": "deny",
                })

                tc = ws.receive_json()
                assert tc["type"] == "turn_complete"

    all_calls = [c for inst in _FakeLayerClient.instances for c in inst.calls]
    assert ("req-deny", False) in all_calls


def test_two_permission_responses_in_one_session():
    """Multiple mid-session frames must ALL be consumed in one turn — not just the first.

    This is the acceptance bar for the recv-loop restructure: the old
    single-shot fall-through only ever looked at one mid-session frame per
    turn, so a second permission_response would be silently dropped (or
    misread by the next outer-loop iteration as a new user message).
    """
    app = _make_app()
    token = _valid_token()
    approved_1 = asyncio.Event()
    approved_2 = asyncio.Event()
    _FakeLayerClient.events["req-1"] = approved_1
    _FakeLayerClient.events["req-2"] = approved_2

    async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
        event_fn = kwargs["event_fn"]
        await event_fn({
            "type": "permission_request", "request_id": "req-1",
            "kind": "user_action", "target": "a", "session_id": "s",
            "reason_from_bot": None,
        })
        await asyncio.wait_for(approved_1.wait(), timeout=5)

        await event_fn({
            "type": "permission_request", "request_id": "req-2",
            "kind": "user_action", "target": "b", "session_id": "s",
            "reason_from_bot": None,
        })
        await asyncio.wait_for(approved_2.wait(), timeout=5)

        send_fn("both handled")

    with patch("api.routes.bot.dispatch_message", new=fake_dispatch), \
         patch("api.routes.bot.LayerClient", new=_FakeLayerClient):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({
                    "type": "user", "content": "go",
                    "agent_version": "tether-agent-2.0",
                })

                p1 = ws.receive_json()
                assert p1["request_id"] == "req-1"
                ws.send_json({
                    "type": "permission_response",
                    "request_id": "req-1", "decision": "approve",
                })

                p2 = ws.receive_json()
                assert p2["request_id"] == "req-2"
                ws.send_json({
                    "type": "permission_response",
                    "request_id": "req-2", "decision": "deny",
                })

                tc = ws.receive_json()
                assert tc["type"] == "turn_complete"
                assert tc["final_text"] == "both handled"

    all_calls = [c for inst in _FakeLayerClient.instances for c in inst.calls]
    assert ("req-1", True) in all_calls
    assert ("req-2", False) in all_calls


def test_layer_error_logged_and_session_continues():
    """respond_to_permission raising must be swallowed — logged, not crashed.

    The gate's own permission timeout is the backstop; a failed POST here
    should not tear down the WebSocket or the session.
    """
    app = _make_app()
    token = _valid_token()

    async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
        event_fn = kwargs["event_fn"]
        await event_fn({
            "type": "permission_request", "request_id": "req-err",
            "kind": "user_action", "target": "x", "session_id": "s",
            "reason_from_bot": None,
        })
        # Session does not wait on approval here — simulates the gate's own
        # timeout eventually firing and letting the turn finish regardless.
        await asyncio.sleep(0.05)
        send_fn("finished despite layer error")

    with patch("api.routes.bot.dispatch_message", new=fake_dispatch), \
         patch("api.routes.bot.LayerClient", new=_RaisingLayerClient):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({
                    "type": "user", "content": "go",
                    "agent_version": "tether-agent-2.0",
                })
                perm = ws.receive_json()
                assert perm["request_id"] == "req-err"

                ws.send_json({
                    "type": "permission_response",
                    "request_id": "req-err", "decision": "approve",
                })

                tc = ws.receive_json()
                assert tc["type"] == "turn_complete"
                assert tc["final_text"] == "finished despite layer error"

                # Connection must stay alive for another message.
                ws.send_json({
                    "type": "user", "content": "still alive?",
                    "agent_version": "tether-agent-2.0",
                })
                # fake_dispatch runs again — will emit another permission_request
                # first; drain it before the final turn_complete.
                perm2 = ws.receive_json()
                assert perm2["request_id"] == "req-err"
                tc2 = ws.receive_json()
                assert tc2["type"] == "turn_complete"


def test_permission_response_missing_request_id_dropped_not_crashed():
    """A malformed permission_response (no request_id) must not crash the handler."""
    app = _make_app()
    token = _valid_token()

    async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
        event_fn = kwargs["event_fn"]
        await event_fn({
            "type": "permission_request", "request_id": "req-1",
            "kind": "user_action", "target": "a", "session_id": "s",
            "reason_from_bot": None,
        })
        await asyncio.sleep(0.05)
        send_fn("done")

    with patch("api.routes.bot.dispatch_message", new=fake_dispatch), \
         patch("api.routes.bot.LayerClient", new=_FakeLayerClient):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({
                    "type": "user", "content": "go",
                    "agent_version": "tether-agent-2.0",
                })
                perm = ws.receive_json()
                assert perm["request_id"] == "req-1"

                # Malformed: no request_id at all.
                ws.send_json({"type": "permission_response", "decision": "approve"})

                tc = ws.receive_json()
                assert tc["type"] == "turn_complete"
                assert tc["final_text"] == "done"

    all_calls = [c for inst in _FakeLayerClient.instances for c in inst.calls]
    assert all_calls == []  # never called — dropped before reaching the layer


def test_unknown_mid_session_frame_still_dropped_with_warning():
    """A frame type that isn't stop or permission_response keeps the old drop+warn behaviour."""
    app = _make_app()
    token = _valid_token()

    async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
        await asyncio.sleep(0.05)
        send_fn("done")

    with patch("api.routes.bot.dispatch_message", new=fake_dispatch):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({
                    "type": "user", "content": "go",
                    "agent_version": "tether-agent-2.0",
                })
                ws.send_json({"type": "some_unknown_frame", "foo": "bar"})

                tc = ws.receive_json()
                assert tc["type"] == "turn_complete"
                assert tc["final_text"] == "done"
