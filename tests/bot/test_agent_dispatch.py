"""Unit tests for bot.agent_dispatch.dispatch_message.

Tests the dispatch matrix:
- tether-agent-1.0 → handle_message called, no stub injected
- tether-agent-2.0 → real LayerClient pipeline; falls back to 1.0 on error or disabled
- tether-agent-2.5 → routes to _dispatch_v25 (M4: paid/admin=premium, free=1.0 fallback)
- unknown / None version → treated as tether-agent-2.0 (layer pipeline default)
- vault/status_fn → forwarded transparently to handle_message (1.0 path)
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest

# Required before any config-loading import.
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fake_handle_1_0_response(text, send_fn, pool, user_id, vault=None, status_fn=None):
    """Fake 1.0 pipeline: delivers a fixed response via send_fn."""
    send_fn("1.0-response")


def _make_mock_vault(oauth_token: str = "sk-ant-test-token"):
    """Return a mock vault whose materialize() yields CLAUDE_CODE_OAUTH_TOKEN."""
    from contextlib import asynccontextmanager
    vault = MagicMock()

    @asynccontextmanager
    async def _materialize(user_id: str):
        yield {"CLAUDE_CODE_OAUTH_TOKEN": oauth_token}

    vault.materialize = _materialize
    return vault


def _assert_not_wired_stub(stub: str) -> None:
    """Stub must communicate not-wired status (matches the wording in agent_dispatch)."""
    stub_lower = stub.lower()
    assert (
        "coming soon" in stub_lower
        or "not yet" in stub_lower
        or "falling back" in stub_lower
    ), f"stub must communicate not-wired status, got: {stub!r}"


def _make_layer_client(*, events=None, raise_on_start=None):
    """Return a mock LayerClient instance and its constructor mock.

    The constructor mock, when called with any args, returns the same instance,
    so patch("bot.agent_dispatch.LayerClient", constructor) works.
    """
    if events is None:
        events = [
            {
                "type": "turn_complete",
                "session_id": "sid-1",
                "final_text": "Layer response",
                "tokens_used": 5,
            }
        ]

    async def _turn_gen(session_id, prompt):
        for event in events:
            yield event

    client = MagicMock()
    client.start_session = AsyncMock(return_value="sid-1")
    client.end_session = AsyncMock()
    client.interrupt = AsyncMock()
    client.turn = _turn_gen

    if raise_on_start is not None:
        client.start_session = AsyncMock(side_effect=raise_on_start)

    constructor = MagicMock(return_value=client)
    return constructor, client


# ---------------------------------------------------------------------------
# 1.0 path — no stub
# ---------------------------------------------------------------------------

async def test_dispatch_1_0_no_stub():
    """tether-agent-1.0 must call handle_message without any stub prepended."""
    with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response):
        from bot.agent_dispatch import dispatch_message

        sent_parts: list[str] = []
        await dispatch_message(
            "tether-agent-1.0",
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
        )
    assert sent_parts == ["1.0-response"], "1.0 path must not inject any stub message"


# ---------------------------------------------------------------------------
# 2.5 path — _dispatch_v25 (M4: paid/admin=premium, free=1.0 fallback)
# ---------------------------------------------------------------------------

async def test_dispatch_25_routes_to_dispatch_v25():
    """tether-agent-2.5 must call _dispatch_v25, not the generic stub."""
    with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response), \
         patch("bot.agent_dispatch._dispatch_v25", AsyncMock()) as mock_v25:

        from bot.agent_dispatch import dispatch_message

        sent: list[str] = []
        await dispatch_message(
            "tether-agent-2.5", "hello",
            send_fn=sent.append, pool=None, user_id="user1",
        )

    mock_v25.assert_awaited_once()
    assert not any("not yet wired" in s for s in sent), \
        "2.5 must not send the generic stub message"


# ---------------------------------------------------------------------------
# Unknown / None version → defaults to 2.0 path (layer pipeline)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "version",
    ["tether-agent-99.0", None],
    ids=["unknown_version", "none_version"],
)
async def test_dispatch_unknown_or_none_defaults_to_2_0_path(version):
    """Unknown or None agent_version must default to tether-agent-2.0 (layer pipeline)."""
    constructor, client = _make_layer_client()
    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        sent_parts: list[str] = []
        await dispatch_message(
            version,
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
            vault=_make_mock_vault(),
        )
    # On success, the layer delivers the final text — no stub, no 1.0 fallback
    assert sent_parts == ["Layer response"]


# ---------------------------------------------------------------------------
# 2.0 real pipeline — happy path
# ---------------------------------------------------------------------------

async def test_dispatch_2_0_creates_layer_session_with_correct_options():
    """2.0 dispatch must call start_session with the correct ClaudeAgentOptions."""
    constructor, client = _make_layer_client()

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message, _V2_0_OPTIONS

        await dispatch_message(
            "tether-agent-2.0",
            "do something",
            send_fn=lambda m: None,
            pool=None,
            user_id="user42",
            vault=_make_mock_vault(),
        )

    constructor.assert_called_once()  # LayerClient instantiated
    client.start_session.assert_awaited_once()
    call_kwargs = client.start_session.call_args

    assert call_kwargs.kwargs.get("user_id") == "user42"
    assert call_kwargs.kwargs.get("agent_version") == "tether-agent-2.0"

    opts = call_kwargs.kwargs.get("options", {})
    assert opts.get("model") == "claude-haiku-4-5-20251001"
    assert opts.get("max_turns") == 2
    assert opts.get("permission_mode") == "auto"
    expected_tools = [
        "upsert_tasks", "upsert_context", "delete_tasks", "delete_context",
        "read_context", "read_tasks", "get_plan", "get_anchors", "search",
    ]
    assert set(opts.get("allowed_tools", [])) == set(expected_tools)


async def test_dispatch_2_0_forwards_conversation_id_to_start_session():
    """conversation_id passed to dispatch_message must reach start_session,
    so the layer can resolve the conversation's scope_source_node_id."""
    constructor, client = _make_layer_client()

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        await dispatch_message(
            "tether-agent-2.0",
            "do something",
            send_fn=lambda m: None,
            pool=None,
            user_id="user42",
            vault=_make_mock_vault(),
            conversation_id="conv-1",
        )

    call_kwargs = client.start_session.call_args
    assert call_kwargs.kwargs.get("conversation_id") == "conv-1"


async def test_dispatch_2_0_conversation_id_optional():
    """conversation_id defaults to None — backwards compatible with existing callers."""
    constructor, client = _make_layer_client()

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        await dispatch_message(
            "tether-agent-2.0",
            "do something",
            send_fn=lambda m: None,
            pool=None,
            user_id="user42",
            vault=_make_mock_vault(),
        )

    call_kwargs = client.start_session.call_args
    assert call_kwargs.kwargs.get("conversation_id") is None


async def test_dispatch_2_0_turn_complete_sends_final_text_and_ends_session():
    """On turn_complete, send_fn must receive final_text and end_session must be called."""
    constructor, client = _make_layer_client(events=[
        {"type": "turn_complete", "session_id": "sid-1", "final_text": "Done!", "tokens_used": 3},
    ])

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        sent_parts: list[str] = []
        await dispatch_message(
            "tether-agent-2.0",
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
            vault=_make_mock_vault(),
        )

    assert sent_parts == ["Done!"]
    client.end_session.assert_awaited_once_with("sid-1")


async def test_dispatch_2_0_status_events_forwarded_via_status_fn():
    """status and agent_action events must be forwarded to status_fn."""
    events = [
        {"type": "status", "session_id": "sid-1", "message": "Thinking..."},
        {"type": "agent_action", "session_id": "sid-1", "action": "Reading your schedule"},
        {"type": "turn_complete", "session_id": "sid-1", "final_text": "Here you go", "tokens_used": 8},
    ]
    constructor, client = _make_layer_client(events=events)
    status_calls: list[str] = []

    async def fake_status_fn(msg: str) -> None:
        status_calls.append(msg)

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        await dispatch_message(
            "tether-agent-2.0",
            "hello",
            send_fn=lambda m: None,
            pool=None,
            user_id="user1",
            status_fn=fake_status_fn,
            vault=_make_mock_vault(),
        )

    assert "Thinking..." in status_calls
    assert "Reading your schedule" in status_calls


# ---------------------------------------------------------------------------
# 2.0 fallback paths
# ---------------------------------------------------------------------------

async def test_dispatch_2_0_layer_disabled_falls_back_to_1_0():
    """When agent_layer.enabled=false, 2.0 must fall back to 1.0 without a stub message."""
    constructor, client = _make_layer_client()

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
        patch("bot.agent_dispatch._layer_enabled", return_value=False),
    ):
        from bot.agent_dispatch import dispatch_message

        sent_parts: list[str] = []
        await dispatch_message(
            "tether-agent-2.0",
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
            vault=_make_mock_vault(),
        )

    # Layer not used
    client.start_session.assert_not_awaited()
    # 1.0 pipeline delivers response silently (no stub prefix)
    assert sent_parts == ["1.0-response"]


async def test_dispatch_2_0_layer_http_error_falls_back_to_1_0():
    """When LayerClient raises an httpx error, 2.0 must silently fall back to 1.0."""
    constructor, client = _make_layer_client(
        raise_on_start=httpx.ConnectError("refused")
    )

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        sent_parts: list[str] = []
        await dispatch_message(
            "tether-agent-2.0",
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
            vault=_make_mock_vault(),
        )

    # 1.0 pipeline must have fired, and no stub message
    assert sent_parts == ["1.0-response"]


async def test_dispatch_2_0_end_session_called_on_http_error():
    """end_session must NOT be called when start_session fails (no session to end)."""
    constructor, client = _make_layer_client(
        raise_on_start=httpx.ConnectError("refused")
    )

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        await dispatch_message(
            "tether-agent-2.0", "hi",
            send_fn=lambda m: None, pool=None, user_id="u1",
            vault=_make_mock_vault(),
        )

    client.end_session.assert_not_awaited()


# ---------------------------------------------------------------------------
# 2.0 event_fn — text delta streaming
# ---------------------------------------------------------------------------

async def test_dispatch_2_0_text_deltas_forwarded_via_event_fn():
    """agent_text_delta events must be forwarded to event_fn."""
    events = [
        {"type": "agent_text_delta", "session_id": "sid-1", "delta": "Hello"},
        {"type": "agent_text_delta", "session_id": "sid-1", "delta": " world"},
        {"type": "turn_complete", "session_id": "sid-1", "final_text": "Hello world", "tokens_used": 5},
    ]
    constructor, _client = _make_layer_client(events=events)
    event_calls: list[dict] = []

    async def fake_event_fn(event: dict) -> None:
        event_calls.append(event)

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        sent_parts: list[str] = []
        await dispatch_message(
            "tether-agent-2.0",
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
            event_fn=fake_event_fn,
            vault=_make_mock_vault(),
        )

    delta_events = [e for e in event_calls if e.get("type") == "agent_text_delta"]
    assert len(delta_events) == 2, "both text deltas must be forwarded"
    assert delta_events[0]["delta"] == "Hello"
    assert delta_events[1]["delta"] == " world"


async def test_dispatch_2_0_send_fn_skipped_when_deltas_sent():
    """When agent_text_delta events are streamed, send_fn must NOT be called at turn_complete."""
    events = [
        {"type": "agent_text_delta", "session_id": "sid-1", "delta": "Hi"},
        {"type": "turn_complete", "session_id": "sid-1", "final_text": "Hi", "tokens_used": 2},
    ]
    constructor, _client = _make_layer_client(events=events)

    async def noop_event_fn(event: dict) -> None:
        pass

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        sent_parts: list[str] = []
        await dispatch_message(
            "tether-agent-2.0",
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
            event_fn=noop_event_fn,
            vault=_make_mock_vault(),
        )

    assert sent_parts == [], "send_fn must not be called when deltas were already streamed"


async def test_dispatch_2_0_send_fn_used_when_no_deltas():
    """When no agent_text_delta events arrive, send_fn must receive final_text at turn_complete."""
    events = [
        {"type": "turn_complete", "session_id": "sid-1", "final_text": "All at once", "tokens_used": 5},
    ]
    constructor, _client = _make_layer_client(events=events)

    async def noop_event_fn(event: dict) -> None:
        pass

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        sent_parts: list[str] = []
        await dispatch_message(
            "tether-agent-2.0",
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
            event_fn=noop_event_fn,
            vault=_make_mock_vault(),
        )

    assert sent_parts == ["All at once"], "send_fn must be called when no deltas were streamed"


async def test_dispatch_2_0_unknown_events_forwarded_via_event_fn():
    """Events that are neither status/agent_action nor known dispatch types must go via event_fn."""
    events = [
        {"type": "permission_request", "session_id": "sid-1", "request_id": "r1", "tool": "delete_tasks"},
        {"type": "turn_complete", "session_id": "sid-1", "final_text": "Done", "tokens_used": 3},
    ]
    constructor, _client = _make_layer_client(events=events)
    event_calls: list[dict] = []

    async def fake_event_fn(event: dict) -> None:
        event_calls.append(event)

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        await dispatch_message(
            "tether-agent-2.0",
            "hello",
            send_fn=lambda m: None,
            pool=None,
            user_id="user1",
            event_fn=fake_event_fn,
            vault=_make_mock_vault(),
        )

    forwarded_types = [e["type"] for e in event_calls]
    assert "permission_request" in forwarded_types, "permission_request must be forwarded via event_fn"


# ---------------------------------------------------------------------------
# turn_error event — layer-side failure surfaced via SSE
# ---------------------------------------------------------------------------

async def test_dispatch_2_0_turn_error_falls_back_to_1_0(caplog):
    """When the layer yields turn_error, dispatch must fall back to 1.0 and log the real message."""
    import logging
    events = [
        {"type": "turn_error", "session_id": "sid-1", "message": "pool_exhausted — retry after 5s"},
    ]
    constructor, _client = _make_layer_client(events=events)

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
        caplog.at_level(logging.WARNING, logger="bot.agent_dispatch"),
    ):
        from bot.agent_dispatch import dispatch_message

        sent_parts: list[str] = []
        await dispatch_message(
            "tether-agent-2.0",
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
            vault=_make_mock_vault(),
        )

    # 1.0 fallback fires
    assert sent_parts == ["1.0-response"], "turn_error must trigger 1.0 fallback"
    # Log must reference the actual pool error, not the generic "layer unavailable"
    assert any("pool_exhausted" in r.message for r in caplog.records), (
        "WARNING log must include the pool error message from turn_error"
    )
    assert not any("layer unavailable" in r.message for r in caplog.records), (
        "turn_error path must not log the misleading 'layer unavailable' message"
    )


async def test_dispatch_2_0_transport_error_logs_turn_transport_error(caplog):
    """Raw httpx transport errors must log 'layer turn transport error', not 'layer unavailable'."""
    import logging
    constructor, client = _make_layer_client(
        raise_on_start=httpx.ConnectError("refused")
    )

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
        caplog.at_level(logging.WARNING, logger="bot.agent_dispatch"),
    ):
        from bot.agent_dispatch import dispatch_message

        await dispatch_message(
            "tether-agent-2.0", "hi",
            send_fn=lambda m: None, pool=None, user_id="u1",
            vault=_make_mock_vault(),
        )

    # The improved log message must say "layer unreachable" or similar, not the old "unavailable"
    assert any(
        "layer unreachable" in r.message or "layer turn transport error" in r.message
        for r in caplog.records
    ), "transport error log must use improved message, not 'layer unavailable'"


# ---------------------------------------------------------------------------
# Existing 1.0 vault/status_fn forwarding test — unchanged
# ---------------------------------------------------------------------------

async def test_dispatch_forwards_vault_and_status_fn():
    """dispatch_message must pass vault and status_fn through to handle_message (1.0 path)."""
    received: dict = {}

    async def capture_kwargs(text, send_fn, pool, user_id, vault=None, status_fn=None):
        received["vault"] = vault
        received["status_fn"] = status_fn

    sentinel_vault = object()
    sentinel_status = AsyncMock()

    with patch("bot.agent_dispatch.handle_message", new=capture_kwargs):
        from bot.agent_dispatch import dispatch_message

        await dispatch_message(
            "tether-agent-1.0",
            "hello",
            send_fn=lambda m: None,
            pool=None,
            user_id="user1",
            vault=sentinel_vault,
            status_fn=sentinel_status,
        )

    assert received["vault"] is sentinel_vault
    assert received["status_fn"] is sentinel_status


# ---------------------------------------------------------------------------
# 2.0 vault token injection
# ---------------------------------------------------------------------------

def _make_mock_vault(oauth_token: str = "sk-ant-dispatch-test"):
    """Return a mock vault whose materialize() yields CLAUDE_CODE_OAUTH_TOKEN."""
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    vault = MagicMock()

    @asynccontextmanager
    async def _materialize(user_id: str):
        yield {"CLAUDE_CODE_OAUTH_TOKEN": oauth_token}

    vault.materialize = _materialize
    return vault


async def test_dispatch_2_0_injects_vault_token_into_options():
    """_dispatch_v2_0 must inject CLAUDE_CODE_OAUTH_TOKEN via vault into start_session options."""
    constructor, client = _make_layer_client()
    vault = _make_mock_vault("sk-ant-oauth-v2-test")

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        await dispatch_message(
            "tether-agent-2.0",
            "do something",
            send_fn=lambda m: None,
            pool=None,
            user_id="user42",
            vault=vault,
        )

    call_kwargs = client.start_session.call_args
    opts = call_kwargs.kwargs.get("options", {})
    assert opts.get("env", {}).get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oauth-v2-test"


async def test_dispatch_2_0_no_vault_falls_back_to_1_0():
    """Without vault (misconfiguration), dispatch_v2_0 must fall back to 1.0 — not fire a
    doomed pool session that will fail auth."""
    constructor, client = _make_layer_client()
    sent_parts: list[str] = []

    with (
        patch("bot.agent_dispatch.LayerClient", constructor),
        patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response),
    ):
        from bot.agent_dispatch import dispatch_message

        await dispatch_message(
            "tether-agent-2.0",
            "do something",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user42",
            vault=None,
        )

    # Must have fallen back to 1.0, not attempted the layer
    assert sent_parts == ["1.0-response"]
    client.start_session.assert_not_awaited()
