"""Unit tests for bot.agent_dispatch.dispatch_message.

Tests the dispatch matrix:
- tether-agent-1.0 → handle_message called, no stub injected
- tether-agent-2.0/2.5 → stub sent via send_fn first, then handle_message called
- unknown / None version → defaults to tether-agent-2.0 path (stub + 1.0 fallback)
- vault/status_fn → forwarded transparently to handle_message
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


async def _fake_handle_1_0_response(text, send_fn, pool, user_id, vault=None, status_fn=None):
    """Fake 1.0 pipeline: delivers a fixed response via send_fn."""
    send_fn("1.0-response")


async def _dispatch(version, **kwargs) -> list[str]:
    """Run dispatch_message under the fake 1.0 pipeline and return captured send_fn parts."""
    with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0_response):
        from bot.agent_dispatch import dispatch_message  # import after patch

        sent_parts: list[str] = []
        await dispatch_message(
            version,
            "hello",
            send_fn=sent_parts.append,
            pool=None,
            user_id="user1",
            **kwargs,
        )
    return sent_parts


def _assert_not_wired_stub(stub: str) -> None:
    """Stub must communicate not-wired status (matches the wording in agent_dispatch)."""
    stub_lower = stub.lower()
    assert (
        "coming soon" in stub_lower
        or "not yet" in stub_lower
        or "falling back" in stub_lower
    ), f"stub must communicate not-wired status, got: {stub!r}"


# ---------------------------------------------------------------------------
# 1.0 path — no stub
# ---------------------------------------------------------------------------

async def test_dispatch_1_0_no_stub():
    """tether-agent-1.0 must call handle_message without any stub prepended."""
    sent_parts = await _dispatch("tether-agent-1.0")
    assert sent_parts == ["1.0-response"], "1.0 path must not inject any stub message"


# ---------------------------------------------------------------------------
# 2.0 / 2.5 paths — stub + 1.0 fallback
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["tether-agent-2.0", "tether-agent-2.5"])
async def test_dispatch_stub_then_calls_1_0(version):
    """2.0/2.5 must prepend a stub mentioning the version, then fall back to 1.0."""
    sent_parts = await _dispatch(version)

    assert len(sent_parts) == 2, f"{version} path must produce stub + 1.0 response"
    stub, response = sent_parts
    version_suffix = version.removeprefix("tether-agent-")
    assert version_suffix in stub, f"stub must mention {version_suffix}, got: {stub!r}"
    _assert_not_wired_stub(stub)
    assert response == "1.0-response"


# ---------------------------------------------------------------------------
# Unknown / None version → defaults to 2.0 path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "version",
    ["tether-agent-99.0", None],
    ids=["unknown_version", "none_version"],
)
async def test_dispatch_unknown_or_none_defaults_to_2_0_path(version):
    """Unknown or None agent_version must default to tether-agent-2.0 (stub + 1.0 fallback)."""
    sent_parts = await _dispatch(version)
    assert len(sent_parts) == 2, (
        f"{version!r} must follow 2.0 path (stub + 1.0 fallback)"
    )


# ---------------------------------------------------------------------------
# vault and status_fn are forwarded transparently
# ---------------------------------------------------------------------------

async def test_dispatch_forwards_vault_and_status_fn():
    """dispatch_message must pass vault and status_fn through to handle_message."""
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
