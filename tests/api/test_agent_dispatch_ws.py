"""WS integration tests for agent_version dispatch routing in bot_chat.

Verifies the bot_chat WebSocket handler routes messages based on agent_version:
- tether-agent-1.0 → no stub, chunk contains only the 1.0 response
- tether-agent-2.0/2.5 → chunk contains stub + 1.0 response (joined by \\n\\n)
- agent_version missing → defaults to 2.0 path (stub + 1.0 response)

Note: The Telegram path (_process_telegram_update) calls handle_message directly
and is intentionally excluded from dispatch routing — it has no picker UI.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-dispatch-ws-tests")

from api.auth import create_jwt  # noqa: E402

TEST_USER_ID = "00000000-0000-0000-0000-000000000097"
TEST_USERNAME = "dispatch_ws_test_user"


class _FakePool:
    """Minimal pool stub — only needed for app.state.pool, not used by dispatch tests."""


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


async def _fake_handle_message(text, send_fn, pool, user_id, vault=None, status_fn=None):
    """Fake 1.0 pipeline: always delivers a fixed response via send_fn."""
    send_fn("1.0-response")


def _dispatch_via_ws(user_message: dict) -> tuple[dict, dict]:
    """Run a single user message through bot_chat and return (chunk, done) frames."""
    from starlette.testclient import TestClient

    app = _make_app()
    token = _valid_token()

    with patch("bot.agent_dispatch.handle_message", new=_fake_handle_message):
        with TestClient(app, raise_server_exceptions=False) as client:
            with client.websocket_connect(
                "/api/bot/chat",
                cookies={"tether_token": token},
            ) as ws:
                ws.send_json({"type": "user", "content": "hello", **user_message})
                chunk = ws.receive_json()
                done = ws.receive_json()
    return chunk, done


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
# tether-agent-2.0 / 2.5 — stub + 1.0 response in chunk
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["tether-agent-2.0", "tether-agent-2.5"])
def test_ws_stub_prepended_for_2x(version):
    """2.0/2.5 must include a stub notice before the 1.0 response in a single chunk frame."""
    chunk, done = _dispatch_via_ws({"agent_version": version})

    assert chunk["type"] == "chunk"
    _assert_stub_present(chunk["content"], version.removeprefix("tether-agent-"))
    assert done["type"] == "done"


# ---------------------------------------------------------------------------
# Missing agent_version — defaults to 2.0 path
# ---------------------------------------------------------------------------

def test_ws_missing_agent_version_defaults_to_2_0():
    """Omitting agent_version must follow the 2.0 path (stub + 1.0 response)."""
    chunk, done = _dispatch_via_ws({})  # agent_version intentionally omitted

    assert chunk["type"] == "chunk"
    content = chunk["content"]
    assert "1.0-response" in content
    content_lower = content.lower()
    assert (
        "coming soon" in content_lower
        or "not yet" in content_lower
        or "falling back" in content_lower
    ), f"missing version must follow 2.0 path (stub present), got chunk: {content!r}"
    assert done["type"] == "done"
