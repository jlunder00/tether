"""Server integration tests for B5a trial counter + B5b BYOK leakage gate.

Tests verify that POST /session/start enforces:
- tether-agent-2.5 + leaky provider → 422 provider_unsupported_for_agent
- tether-agent-2.5 + is_paid=True → counter bypassed, session created
- tether-agent-2.5 + is_paid=False + counter allows → session created, trial_usage_update published
- tether-agent-2.5 + is_paid=False + counter exhausted → 422 trial_exhausted
- tether-agent-1.0 / 2.0 → no gate, always allowed

These tests inject mock trial_counter, is_paid_fn, and provider_fn via the Layer
constructor (no real DB needed).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport


_START_BODY_BASE = {
    "user_ws_id": "ws-001",
    "options": {},
    "user_message": "hello",
}


def _start_body(user_id: str = "user-1", agent_version: str = "tether-agent-2.5") -> dict:
    return {"user_id": user_id, "agent_version": agent_version, **_START_BODY_BASE}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _MockTrialCounter:
    def __init__(self, allowed: bool = True, remaining: int = 5):
        self._allowed = allowed
        self._remaining = remaining
        self.calls: list[str] = []

    async def check_and_increment(self, user_id: str):
        self.calls.append(user_id)
        return self._allowed, self._remaining


def _make_layer(
    *,
    is_paid: bool = False,
    trial_allowed: bool = True,
    trial_remaining: int = 5,
    provider: str = "anthropic_oauth",
    leaky_providers: list[str] | None = None,
):
    """Build a Layer with injected mock gate dependencies."""
    import pathlib
    from interactive_agent_layer.ws_publisher import WSPublisher
    from interactive_agent_layer.session import Layer
    from interactive_agent_layer.translation import TranslationTable

    if leaky_providers is None:
        leaky_providers = ["openrouter", "openai"]

    yaml_path = (
        pathlib.Path(__file__).parent.parent.parent / "config" / "agent_translations.yaml"
    )
    translation_table = TranslationTable.from_yaml(yaml_path)

    class _FakePool:
        async def acquire(self):
            return None

    trial_counter = _MockTrialCounter(allowed=trial_allowed, remaining=trial_remaining)
    is_paid_fn = AsyncMock(return_value=is_paid)
    provider_fn = MagicMock(return_value=provider)

    ws_publisher = WSPublisher()

    # MockPoolClient is only needed for run_turn, not session_start
    class _MockPoolClient:
        async def acquire(self, *a, **kw): return "handle"
        async def query(self, *a, **kw): return; yield  # noqa: E704
        async def release(self, *a, **kw): pass
        async def interrupt(self, *a, **kw): pass

    return Layer(
        pool_client=_MockPoolClient(),
        ws_publisher=ws_publisher,
        translation_table=translation_table,
        trial_counter=trial_counter,
        is_paid_fn=is_paid_fn,
        provider_fn=provider_fn,
        leaky_providers=leaky_providers,
    ), trial_counter, is_paid_fn, ws_publisher


@asynccontextmanager
async def _client_for(layer):
    from interactive_agent_layer.server import create_app
    app = create_app(layer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# B5b — BYOK leakage gate
# ---------------------------------------------------------------------------

async def test_session_start_2_5_leaky_provider_rejected():
    """tether-agent-2.5 with a leaky provider returns 422 provider_unsupported_for_agent."""
    layer, _, _, _ = _make_layer(provider="openrouter", leaky_providers=["openrouter", "openai"])
    async with _client_for(layer) as client:
        resp = await client.post("/session/start", json=_start_body(agent_version="tether-agent-2.5"))

    assert resp.status_code == 422
    body = resp.json()
    assert body.get("error") == "provider_unsupported_for_agent"
    assert "tether-agent-2.0" in body.get("alternatives", [])


async def test_session_start_2_5_safe_provider_allowed():
    """tether-agent-2.5 with anthropic_oauth (safe provider) passes the leakage gate."""
    layer, _, _, _ = _make_layer(provider="anthropic_oauth", trial_allowed=True)
    async with _client_for(layer) as client:
        resp = await client.post("/session/start", json=_start_body(agent_version="tether-agent-2.5"))

    assert resp.status_code == 200
    assert "session_id" in resp.json()


# ---------------------------------------------------------------------------
# B5a — trial counter: premium bypass
# ---------------------------------------------------------------------------

async def test_session_start_2_5_premium_bypasses_counter():
    """is_paid=True: trial counter is never called, session is created."""
    layer, trial_counter, _, _ = _make_layer(is_paid=True, trial_allowed=False)
    async with _client_for(layer) as client:
        resp = await client.post("/session/start", json=_start_body(agent_version="tether-agent-2.5"))

    assert resp.status_code == 200
    assert "session_id" in resp.json()
    assert trial_counter.calls == [], "premium user must not touch the trial counter"


# ---------------------------------------------------------------------------
# B5a — trial counter: free user allowed
# ---------------------------------------------------------------------------

async def test_session_start_2_5_free_user_counter_increments():
    """is_paid=False + counter allows: session created, counter incremented."""
    layer, trial_counter, _, _ = _make_layer(is_paid=False, trial_allowed=True, trial_remaining=4)
    async with _client_for(layer) as client:
        resp = await client.post("/session/start", json=_start_body(user_id="free-user"))

    assert resp.status_code == 200
    assert "session_id" in resp.json()
    assert "free-user" in trial_counter.calls, "trial counter must be called for free user"


# ---------------------------------------------------------------------------
# B5a — trial counter: free user exhausted
# ---------------------------------------------------------------------------

async def test_session_start_2_5_trial_exhausted():
    """is_paid=False + counter exhausted: returns 422 trial_exhausted."""
    layer, _, _, _ = _make_layer(is_paid=False, trial_allowed=False, trial_remaining=0)
    async with _client_for(layer) as client:
        resp = await client.post("/session/start", json=_start_body(agent_version="tether-agent-2.5"))

    assert resp.status_code == 422
    body = resp.json()
    assert body.get("error") == "trial_exhausted"
    assert "upgrade_url" in body


# ---------------------------------------------------------------------------
# B5a — trial_usage_update published after allowed 2.5 session
# ---------------------------------------------------------------------------

async def test_session_start_2_5_publishes_trial_usage_update():
    """Successful 2.5 session start publishes trial_usage_update WS event with remaining count."""
    layer, _, _, ws_publisher = _make_layer(is_paid=False, trial_allowed=True, trial_remaining=7)
    published: list[dict] = []
    ws_publisher.push = AsyncMock(side_effect=lambda ws_id, event, **_: published.append(event))

    async with _client_for(layer) as client:
        await client.post("/session/start", json=_start_body(user_id="user-trial"))

    trial_events = [e for e in published if e.get("type") == "trial_usage_update"]
    assert trial_events, "trial_usage_update event must be published"
    event = trial_events[0]
    assert event["remaining"] == 7


# ---------------------------------------------------------------------------
# No gate for 1.0 and 2.0
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["tether-agent-1.0", "tether-agent-2.0"])
async def test_session_start_no_gate_for_1_0_and_2_0(version):
    """1.0 and 2.0 bypass all gate checks — always allowed regardless of provider or tier."""
    # Leaky provider + exhausted counter + free user: still must succeed for 1.0/2.0
    layer, trial_counter, is_paid_fn, _ = _make_layer(
        is_paid=False,
        trial_allowed=False,
        provider="openrouter",
        leaky_providers=["openrouter"],
    )
    async with _client_for(layer) as client:
        resp = await client.post("/session/start", json=_start_body(agent_version=version))

    assert resp.status_code == 200, f"{version} must bypass gate (got {resp.status_code})"
    assert trial_counter.calls == [], f"{version} must not touch trial counter"
    is_paid_fn.assert_not_called()
