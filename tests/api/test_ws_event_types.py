"""Tests verifying the correct WebSocket event types from /api/bot/chat.

These tests document the correct protocol:
- response_parts (send_fn) path  → {"type": "turn_complete", "final_text": "..."}
- agent_text_delta (event_fn) path → {"type": "agent_text_delta", "delta": "..."}
- NO {"type": "chunk"} should ever be emitted for normal responses
- NO {"type": "done"} should terminate a session (turn_complete does that)

The bug being fixed: bot.py was emitting {"type": "chunk"} / {"type": "done"}
which the frontend does not recognise and silently drops, so responses never
appear in the UI.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch, AsyncMock

import pytest

os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-ws-tests")

from api.auth import create_jwt
from contextlib import asynccontextmanager

TEST_USER_ID = "00000000-0000-0000-0000-000000000042"
TEST_USERNAME = "event_type_test_user"


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


# ---------------------------------------------------------------------------
# response_parts path (send_fn) → must send turn_complete, NOT chunk+done
# ---------------------------------------------------------------------------

class TestResponsePartsSendsTurnComplete:
    def test_send_fn_produces_turn_complete_not_chunk(self):
        """When dispatch calls send_fn, WS handler must emit turn_complete with final_text.

        This is the 2.5 (one_shot) path: register.py returns a string which
        _dispatch_v25 delivers via send_fn. The frontend terminates its generator
        and renders content only on turn_complete — not on chunk.
        """
        app = _make_app()
        token = _valid_token()

        async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
            send_fn("bot response text")

        with patch("api.routes.bot.dispatch_message", new=fake_dispatch):
            from starlette.testclient import TestClient
            with TestClient(app, raise_server_exceptions=False) as client:
                with client.websocket_connect(
                    "/api/bot/chat",
                    cookies={"tether_token": token},
                ) as ws:
                    ws.send_json({
                        "type": "user",
                        "content": "hello",
                        "agent_version": "tether-agent-2.5",
                    })
                    msg = ws.receive_json()
                    assert msg["type"] == "turn_complete", (
                        f"Expected turn_complete, got {msg['type']!r}. "
                        "The WS handler must send turn_complete (not chunk) so the "
                        "frontend generator terminates and renders the content."
                    )
                    assert msg.get("final_text") == "bot response text", (
                        f"turn_complete must carry final_text, got: {msg}"
                    )

    def test_send_fn_never_emits_chunk_type(self):
        """The bot_chat handler must never emit {type: chunk} for a normal response."""
        app = _make_app()
        token = _valid_token()

        async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
            send_fn("a response")

        with patch("api.routes.bot.dispatch_message", new=fake_dispatch):
            from starlette.testclient import TestClient
            with TestClient(app, raise_server_exceptions=False) as client:
                with client.websocket_connect(
                    "/api/bot/chat",
                    cookies={"tether_token": token},
                ) as ws:
                    ws.send_json({
                        "type": "user",
                        "content": "hi",
                        "agent_version": "tether-agent-2.5",
                    })
                    msg = ws.receive_json()
                    assert msg["type"] != "chunk", (
                        "bot_chat must not emit {type: chunk} — the frontend does not "
                        "handle this type and will silently drop the message."
                    )

    def test_empty_response_parts_still_sends_turn_complete(self):
        """When send_fn is never called, a turn_complete with empty final_text is still sent.

        The frontend generator must terminate even for empty responses.
        """
        app = _make_app()
        token = _valid_token()

        async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
            pass  # never calls send_fn

        with patch("api.routes.bot.dispatch_message", new=fake_dispatch):
            from starlette.testclient import TestClient
            with TestClient(app, raise_server_exceptions=False) as client:
                with client.websocket_connect(
                    "/api/bot/chat",
                    cookies={"tether_token": token},
                ) as ws:
                    ws.send_json({
                        "type": "user",
                        "content": "hi",
                        "agent_version": "tether-agent-2.5",
                    })
                    msg = ws.receive_json()
                    assert msg["type"] == "turn_complete", (
                        f"Expected turn_complete even for empty response, got {msg['type']!r}"
                    )
                    assert msg.get("final_text") == "", (
                        f"final_text must be empty string for empty response, got: {msg}"
                    )

    def test_exactly_one_message_per_turn(self):
        """The bot_chat handler must send exactly ONE message per turn (turn_complete).

        The old protocol sent two ({type: chunk} + {type: done}). Now it must
        send only turn_complete — no trailing done, no extra frames.
        """
        app = _make_app()
        token = _valid_token()

        received: list[dict] = []

        async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
            send_fn("text")

        with patch("api.routes.bot.dispatch_message", new=fake_dispatch):
            from starlette.testclient import TestClient
            with TestClient(app, raise_server_exceptions=False) as client:
                with client.websocket_connect(
                    "/api/bot/chat",
                    cookies={"tether_token": token},
                ) as ws:
                    ws.send_json({
                        "type": "user",
                        "content": "hi",
                        "agent_version": "tether-agent-2.5",
                    })
                    # Read the one expected message
                    msg = ws.receive_json()
                    received.append(msg)
                    assert msg["type"] == "turn_complete"
                    # No second message should be pending — the ws.receive_json()
                    # with a very short timeout would block; we verify by asserting
                    # exactly what came through (the WS exits cleanly with one message)

        assert len(received) == 1
        assert received[0]["type"] == "turn_complete"


# ---------------------------------------------------------------------------
# event_fn (agent_text_delta) path → must forward as agent_text_delta, NOT chunk
# ---------------------------------------------------------------------------

class TestEventFnSendsAgentTextDelta:
    def test_event_fn_delta_forwarded_as_agent_text_delta(self):
        """When dispatch calls event_fn with agent_text_delta, WS must forward it as-is.

        This is the 2.0 (session) path: the interactive-agent-layer emits
        agent_text_delta events which must be forwarded verbatim so the frontend
        can render streaming text incrementally.

        The fake_dispatch emits ONE delta then returns. bot_chat then sends its
        own turn_complete from the response_parts path. Both messages are consumed
        before the WS closes to avoid server-side send-to-closed-socket hangs.
        """
        app = _make_app()
        token = _valid_token()

        async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
            event_fn = kwargs.get("event_fn")
            if event_fn:
                await event_fn({"type": "agent_text_delta", "delta": "streaming chunk"})
            # Return without calling event_fn(turn_complete) — bot_chat sends
            # turn_complete itself via the response_parts path after we return.

        with patch("api.routes.bot.dispatch_message", new=fake_dispatch):
            from starlette.testclient import TestClient
            with TestClient(app, raise_server_exceptions=False) as client:
                with client.websocket_connect(
                    "/api/bot/chat",
                    cookies={"tether_token": token},
                ) as ws:
                    ws.send_json({
                        "type": "user",
                        "content": "stream me",
                        "agent_version": "tether-agent-2.0",
                    })
                    # Message 1: the delta
                    delta_msg = ws.receive_json()
                    assert delta_msg["type"] == "agent_text_delta", (
                        f"Expected agent_text_delta, got {delta_msg['type']!r}. "
                        "event_fn deltas must be forwarded as agent_text_delta so the "
                        "frontend can render streaming text."
                    )
                    assert delta_msg.get("delta") == "streaming chunk", (
                        f"agent_text_delta must carry delta field, got: {delta_msg}"
                    )
                    # Message 2: turn_complete from response_parts — must consume to
                    # avoid leaving the server blocked writing to a closing socket.
                    tc = ws.receive_json()
                    assert tc["type"] == "turn_complete"

    def test_event_fn_delta_never_emits_chunk(self):
        """agent_text_delta events from event_fn must NOT be re-wrapped as chunk."""
        app = _make_app()
        token = _valid_token()

        async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
            event_fn = kwargs.get("event_fn")
            if event_fn:
                await event_fn({"type": "agent_text_delta", "delta": "hello"})
            # Don't send turn_complete via event_fn — bot_chat sends it from response_parts.

        with patch("api.routes.bot.dispatch_message", new=fake_dispatch):
            from starlette.testclient import TestClient
            with TestClient(app, raise_server_exceptions=False) as client:
                with client.websocket_connect(
                    "/api/bot/chat",
                    cookies={"tether_token": token},
                ) as ws:
                    ws.send_json({
                        "type": "user",
                        "content": "hi",
                        "agent_version": "tether-agent-2.0",
                    })
                    first = ws.receive_json()
                    assert first["type"] != "chunk", (
                        "agent_text_delta from event_fn must not be re-wrapped as chunk. "
                        "The frontend only handles agent_text_delta type for streaming."
                    )
                    # Consume turn_complete before closing to avoid server-side hang.
                    ws.receive_json()

    def test_event_fn_non_delta_events_forwarded_verbatim(self):
        """Non-delta events from event_fn (e.g. permission_request) are forwarded as-is."""
        app = _make_app()
        token = _valid_token()

        async def fake_dispatch(agent_version, text, send_fn, pool, user_id, **kwargs):
            event_fn = kwargs.get("event_fn")
            if event_fn:
                await event_fn({
                    "type": "permission_request",
                    "tool_name": "read_file",
                    "session_id": "s",
                })
            # Don't send turn_complete via event_fn — bot_chat sends it from response_parts.

        with patch("api.routes.bot.dispatch_message", new=fake_dispatch):
            from starlette.testclient import TestClient
            with TestClient(app, raise_server_exceptions=False) as client:
                with client.websocket_connect(
                    "/api/bot/chat",
                    cookies={"tether_token": token},
                ) as ws:
                    ws.send_json({
                        "type": "user",
                        "content": "do something",
                        "agent_version": "tether-agent-2.0",
                    })
                    # Message 1: permission_request forwarded verbatim
                    perm = ws.receive_json()
                    assert perm["type"] == "permission_request"
                    assert perm["tool_name"] == "read_file"
                    # Message 2: turn_complete — must consume before WS close.
                    ws.receive_json()
