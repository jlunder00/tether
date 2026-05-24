"""WS integration tests for agent_version dispatch routing in bot_chat.

Verifies the bot_chat WebSocket handler routes messages based on agent_version:
- tether-agent-1.0 → no stub, chunk contains only the 1.0 response
- tether-agent-2.0 → real layer pipeline; falls back silently to 1.0 on error
- tether-agent-2.5 → free user: upgrade notice + 1.0 fallback (M4)
- agent_version missing → defaults to 2.0 path (layer pipeline / fallback)

Note: The Telegram path (_process_telegram_update) calls handle_message directly
and is intentionally excluded from dispatch routing — it has no picker UI.

Deliberate behaviour change (M3): tether-agent-2.0 no longer sends a user-
visible stub. It runs the real layer pipeline, falling back silently to 1.0
when the layer is unavailable. This is tested both with a mocked successful
layer session and with a mocked HTTP failure.

Deliberate behaviour change (M4): tether-agent-2.5 no longer sends the generic
"not yet wired" stub. Free users see a Pro-plan upgrade notice; paid/admin users
reach the premium handler. This WS test uses a non-admin, no-DB token so the
free user path executes.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-dispatch-ws-tests")

from api.auth import create_jwt  # noqa: E402

TEST_USER_ID = "00000000-0000-0000-0000-000000000097"
TEST_USERNAME = "dispatch_ws_test_user"


class _FakePool:
    """Minimal pool stub — only needed for app.state.pool, not used by dispatch tests."""


def _make_mock_vault(oauth_token: str = "sk-ant-ws-test-token"):
    """Return a mock vault whose materialize() yields CLAUDE_CODE_OAUTH_TOKEN."""
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock
    vault = MagicMock()

    @asynccontextmanager
    async def _materialize(user_id: str):
        yield {"CLAUDE_CODE_OAUTH_TOKEN": oauth_token}

    vault.materialize = _materialize
    return vault


@asynccontextmanager
async def _noop_lifespan(app):
    app.state.pool = _FakePool()
    app.state.vault = _make_mock_vault()
    yield


def _make_app():
    from api.main import create_app
    return create_app(lifespan_override=_noop_lifespan)


def _valid_token():
    return create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)


async def _fake_handle_message(text, send_fn, pool, user_id, vault=None, status_fn=None):
    """Fake 1.0 pipeline: always delivers a fixed response via send_fn."""
    send_fn("1.0-response")


def _make_layer_constructor(*, events=None, raise_on_start=None):
    """Return a LayerClient constructor mock yielding the given events on turn()."""
    if events is None:
        events = [
            {
                "type": "turn_complete",
                "session_id": "sid-ws",
                "final_text": "Layer WS response",
                "tokens_used": 5,
            }
        ]

    async def _turn_gen(session_id, prompt):
        for event in events:
            yield event

    client = MagicMock()
    if raise_on_start:
        client.start_session = AsyncMock(side_effect=raise_on_start)
    else:
        client.start_session = AsyncMock(return_value="sid-ws")
    client.end_session = AsyncMock()
    client.interrupt = AsyncMock()
    client.turn = _turn_gen

    return MagicMock(return_value=client), client


def _dispatch_via_ws(user_message: dict, extra_patches=None) -> tuple[dict, dict]:
    """Run a single user message through bot_chat and return (chunk, done) frames.

    For non-streaming responses only (one chunk + done). Use _dispatch_via_ws_all
    when testing streaming (multiple chunk frames before done).

    extra_patches: list of (target, mock) tuples for additional patch.object calls.
    """
    frames = _dispatch_via_ws_all(user_message, extra_patches=extra_patches)
    chunks = [f for f in frames if f["type"] == "chunk"]
    dones = [f for f in frames if f["type"] == "done"]
    # Collapse multiple chunks into one for backward compat with existing tests
    if len(chunks) > 1:
        combined = "\n\n".join(c["content"] for c in chunks)
        return {"type": "chunk", "content": combined}, dones[0]
    return chunks[0] if chunks else {"type": "chunk", "content": ""}, dones[0]


def _dispatch_via_ws_all(user_message: dict, extra_patches=None) -> list[dict]:
    """Run a single user message through bot_chat and return ALL frames received until done."""
    from starlette.testclient import TestClient

    app = _make_app()
    token = _valid_token()
    patches = extra_patches or []

    ctx = [patch("bot.agent_dispatch.handle_message", new=_fake_handle_message)]
    for target, new in patches:
        ctx.append(patch(target, new))

    import contextlib
    with contextlib.ExitStack() as stack:
        for p in ctx:
            stack.enter_context(p)
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "hello", **user_message})
                frames: list[dict] = []
                while True:
                    frame = ws.receive_json()
                    frames.append(frame)
                    if frame.get("type") == "done":
                        break
    return frames


def _assert_stub_present(content: str, version_suffix: str) -> None:
    """Chunk content must include the 1.0 response and a stub mentioning the version."""
    assert "1.0-response" in content, "1.0 response must be present in chunk"
    assert version_suffix in content, f"stub must mention agent version {version_suffix}"
    content_lower = content.lower()
    assert (
        "coming soon" in content_lower
        or "not yet" in content_lower
        or "falling back" in content_lower
    ), f"stub must communicate not-wired status, got chunk: {content!r}"


# ---------------------------------------------------------------------------
# tether-agent-1.0 — no stub in response
# ---------------------------------------------------------------------------

def test_ws_agent_1_0_no_stub():
    """tether-agent-1.0 must produce chunk('1.0-response') with no stub prepended."""
    chunk, done = _dispatch_via_ws({"agent_version": "tether-agent-1.0"})

    assert chunk["type"] == "chunk"
    assert chunk["content"] == "1.0-response", (
        "1.0 must not prepend a stub — response must be exactly '1.0-response'"
    )
    assert done["type"] == "done"


# ---------------------------------------------------------------------------
# tether-agent-2.5 — M4: free user gets upgrade notice + 1.0 fallback
# ---------------------------------------------------------------------------

def test_ws_2_5_free_user_gets_upgrade_notice():
    """2.5 free user: must see Pro-plan upgrade notice and receive 1.0 response.

    Test uses a non-admin token and no DB pool, so subscription check fails
    (defaults to free).  _dispatch_v25 must send the upgrade notice then fall
    back to handle_message (1.0 pipeline).
    """
    chunk, done = _dispatch_via_ws({"agent_version": "tether-agent-2.5"})

    combined = chunk.get("content", "")
    assert chunk["type"] == "chunk"
    assert "1.0-response" in combined, "1.0 fallback must be present"
    combined_lower = combined.lower()
    assert (
        "pro plan" in combined_lower
        or "free plan" in combined_lower
        or "pro" in combined_lower
    ), f"upgrade notice must mention Pro/free plan, got: {combined!r}"
    # Must NOT include the old not-yet-wired generic stub
    assert "not yet wired" not in combined_lower, \
        "2.5 must not send the generic 'not yet wired' stub"
    assert done["type"] == "done"


# ---------------------------------------------------------------------------
# tether-agent-2.0 — real layer pipeline
# ---------------------------------------------------------------------------

def test_ws_2_0_layer_delivers_response():
    """2.0 real pipeline: layer turn_complete final_text must arrive as the chunk."""
    constructor, client = _make_layer_constructor()
    chunk, done = _dispatch_via_ws(
        {"agent_version": "tether-agent-2.0"},
        extra_patches=[("bot.agent_dispatch.LayerClient", constructor)],
    )

    assert chunk["type"] == "chunk"
    assert chunk["content"] == "Layer WS response"
    assert done["type"] == "done"


def test_ws_2_0_layer_unavailable_falls_back_silently():
    """2.0 path: when layer is unavailable, fall back to 1.0 — no stub in chunk."""
    import httpx
    constructor, _client = _make_layer_constructor(
        raise_on_start=httpx.ConnectError("refused")
    )
    chunk, done = _dispatch_via_ws(
        {"agent_version": "tether-agent-2.0"},
        extra_patches=[("bot.agent_dispatch.LayerClient", constructor)],
    )

    assert chunk["type"] == "chunk"
    # No stub — silent fallback, user just gets the 1.0 response
    assert chunk["content"] == "1.0-response"
    content_lower = chunk["content"].lower()
    assert "coming soon" not in content_lower
    assert "not yet" not in content_lower
    assert done["type"] == "done"


# ---------------------------------------------------------------------------
# Missing agent_version — defaults to 2.0 path
# ---------------------------------------------------------------------------

def test_ws_missing_agent_version_defaults_to_2_0_layer_path():
    """Omitting agent_version defaults to 2.0 (real layer pipeline / silent fallback)."""
    import httpx
    constructor, _client = _make_layer_constructor(
        raise_on_start=httpx.ConnectError("refused")
    )
    chunk, done = _dispatch_via_ws(
        {},  # agent_version intentionally omitted
        extra_patches=[("bot.agent_dispatch.LayerClient", constructor)],
    )

    assert chunk["type"] == "chunk"
    # 2.0 fallback: 1.0-response, no stub
    assert chunk["content"] == "1.0-response"
    assert "coming soon" not in chunk["content"].lower()
    assert done["type"] == "done"


# ---------------------------------------------------------------------------
# tether-agent-2.0 — streaming text deltas via event_fn
# ---------------------------------------------------------------------------

def test_ws_2_0_text_deltas_arrive_as_chunk_frames():
    """agent_text_delta events must arrive as individual chunk frames before done."""
    events = [
        {"type": "agent_text_delta", "session_id": "sid-ws", "delta": "Hello"},
        {"type": "agent_text_delta", "session_id": "sid-ws", "delta": " world"},
        {"type": "turn_complete", "session_id": "sid-ws", "final_text": "Hello world", "tokens_used": 5},
    ]
    constructor, _client = _make_layer_constructor(events=events)
    frames = _dispatch_via_ws_all(
        {"agent_version": "tether-agent-2.0"},
        extra_patches=[("bot.agent_dispatch.LayerClient", constructor)],
    )

    chunk_frames = [f for f in frames if f["type"] == "chunk"]
    done_frames = [f for f in frames if f["type"] == "done"]

    assert len(chunk_frames) == 2, "two delta events must produce two chunk frames"
    assert chunk_frames[0]["content"] == "Hello"
    assert chunk_frames[1]["content"] == " world"
    assert len(done_frames) == 1


def test_ws_2_0_no_duplicate_chunk_after_streaming():
    """When deltas are streamed, final_text must NOT be sent as an extra chunk frame."""
    events = [
        {"type": "agent_text_delta", "session_id": "sid-ws", "delta": "Hi"},
        {"type": "turn_complete", "session_id": "sid-ws", "final_text": "Hi", "tokens_used": 2},
    ]
    constructor, _client = _make_layer_constructor(events=events)
    frames = _dispatch_via_ws_all(
        {"agent_version": "tether-agent-2.0"},
        extra_patches=[("bot.agent_dispatch.LayerClient", constructor)],
    )

    chunk_frames = [f for f in frames if f["type"] == "chunk"]
    # Only one delta chunk — no duplicate final_text chunk
    assert len(chunk_frames) == 1
    assert chunk_frames[0]["content"] == "Hi"


def test_ws_2_0_non_streaming_still_sends_final_chunk():
    """When no deltas arrive, final_text must still arrive as a single chunk frame."""
    events = [
        {"type": "turn_complete", "session_id": "sid-ws", "final_text": "All at once", "tokens_used": 4},
    ]
    constructor, _client = _make_layer_constructor(events=events)
    frames = _dispatch_via_ws_all(
        {"agent_version": "tether-agent-2.0"},
        extra_patches=[("bot.agent_dispatch.LayerClient", constructor)],
    )

    chunk_frames = [f for f in frames if f["type"] == "chunk"]
    assert len(chunk_frames) == 1
    assert chunk_frames[0]["content"] == "All at once"
