"""Tests that POST /session/start fires a best-effort pool hint.

Belt-and-suspenders: even if the FE hint missed, session creation triggers
a warm so the first turn is less likely to face a cold pool.
"""
from __future__ import annotations

import asyncio
import pathlib

import pytest
from httpx import AsyncClient, ASGITransport

from interactive_agent_layer.ws_publisher import WSPublisher
from interactive_agent_layer.session import Layer
from interactive_agent_layer.translation import TranslationTable


# ---------------------------------------------------------------------------
# Mock pool client that records hint calls
# ---------------------------------------------------------------------------

class _HintCapturingPoolClient:
    """Pool client that records hint() calls and optionally raises."""

    def __init__(self, *, raise_on_hint: bool = False):
        self.hint_calls: list[tuple] = []
        self._raise = raise_on_hint

    async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
        return "mock-handle"

    async def query_stream(self, handle_id, prompt, session_id="default"):
        yield {"type": "result", "final_text": "done", "tokens_used": 0}

    async def release(self, handle_id, *, reusable=False):
        pass

    async def interrupt(self, handle_id):
        pass

    async def hint(self, user_id: str, options_hash: str, options: dict) -> None:
        self.hint_calls.append((user_id, options_hash, options))
        if self._raise:
            raise RuntimeError("pool hint failed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_config_getters(monkeypatch):
    monkeypatch.setattr(
        "interactive_agent_layer.session.get_auto_approve_user_actions",
        lambda: False,
    )


def _make_layer(pool_client) -> Layer:
    yaml_path = pathlib.Path(__file__).parent.parent.parent / "config" / "agent_translations.yaml"
    return Layer(
        pool_client=pool_client,
        ws_publisher=WSPublisher(),
        translation_table=TranslationTable.from_yaml(yaml_path),
    )


@pytest.fixture
async def hint_client():
    """Layer app with a hint-capturing pool client."""
    pool_client = _HintCapturingPoolClient()
    layer = _make_layer(pool_client)
    from interactive_agent_layer.server import create_app
    app = create_app(layer)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, pool_client


@pytest.fixture
async def hint_failing_client():
    """Layer app with a pool client whose hint() raises."""
    pool_client = _HintCapturingPoolClient(raise_on_hint=True)
    layer = _make_layer(pool_client)
    from interactive_agent_layer.server import create_app
    app = create_app(layer)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, pool_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_session_start_fires_pool_hint(hint_client):
    """POST /session/start fires pool_client.hint for the session's options."""
    client, pool = hint_client

    resp = await client.post(
        "/session/start",
        json={
            "user_id": "user-hint-1",
            "user_ws_id": "ws-1",
            "agent_version": "tether-agent-2.0",
            "options": {"model": "claude-haiku-4-5-20251001"},
            "user_message": "hello",
        },
    )
    assert resp.status_code == 200
    # Give the background task a moment to run
    await asyncio.sleep(0.05)

    assert len(pool.hint_calls) == 1
    user_id, options_hash, options = pool.hint_calls[0]
    assert user_id == "user-hint-1"
    assert len(options_hash) == 16


async def test_session_start_hint_failure_does_not_block_response(hint_failing_client):
    """POST /session/start returns 200 even when pool hint raises."""
    client, pool = hint_failing_client

    resp = await client.post(
        "/session/start",
        json={
            "user_id": "user-hint-fail",
            "user_ws_id": "ws-fail",
            "agent_version": "tether-agent-2.0",
            "options": {},
            "user_message": "hi",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data


async def test_session_start_hint_uses_session_options(hint_client):
    """Pool hint receives same options dict as passed in session start."""
    client, pool = hint_client
    test_options = {"model": "sonnet-4.5", "allowed_tools": ["get_anchors"]}

    await client.post(
        "/session/start",
        json={
            "user_id": "user-opts",
            "user_ws_id": "ws-opts",
            "agent_version": "tether-agent-2.0",
            "options": test_options,
            "user_message": "check options",
        },
    )
    await asyncio.sleep(0.05)

    assert len(pool.hint_calls) == 1
    _, _, hinted_options = pool.hint_calls[0]
    assert hinted_options == test_options
