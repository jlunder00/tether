"""Tests for tether-agent-2.5 dispatch path in agent_dispatch.py.

M4 wires a real 2.5 path: paid users get the premium session handler;
free users receive an upgrade notice and fall back to tether-agent-1.0.

All DB and premium-package interactions are fully mocked.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Must be set before config loading is triggered (jwt.secret is required).
os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-tests")

TEST_USER_ID = "00000000-0000-0000-0000-000000000042"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fake_handle_1_0(text, send_fn, pool, user_id, vault=None, status_fn=None):
    send_fn("1.0-response")


def _make_conn_ctx(is_paid_return=False):
    """Mock async context manager that yields a conn where get_user_is_paid returns is_paid_return."""
    mock_conn = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# _dispatch_v25() — must exist and behave correctly
# ---------------------------------------------------------------------------

class TestDispatchV25:
    @pytest.mark.asyncio
    async def test_free_user_gets_notice_and_10_fallback(self):
        """Free user: upgrade notice sent, 1.0 handle_message called."""
        sent = []

        with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=False)):

            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("do a task", sent.append, None, TEST_USER_ID)

        # An upgrade/fallback notice was sent before the 1.0 response
        assert len(sent) >= 2, f"Expected notice + 1.0-response, got: {sent}"
        assert any(
            "pro" in s.lower() or "paid" in s.lower() or "1.0" in s or "free" in s.lower()
            for s in sent
        ), f"Free user must see upgrade/fallback notice. Got: {sent}"
        assert "1.0-response" in sent

    @pytest.mark.asyncio
    async def test_paid_user_calls_premium_and_no_stub(self):
        """Paid user: premium handler called, no upgrade/stub notice sent."""
        import sys

        sent = []
        mock_premium_handler = AsyncMock(return_value="Premium reply")

        # Inject a fake tether_premium.register into sys.modules so the
        # lazy import inside _dispatch_v25 succeeds without tether-premium installed.
        mock_register = MagicMock()
        # get_premium_handler() → the handler callable
        mock_register.get_premium_handler = MagicMock(return_value=mock_premium_handler)
        mock_tether_premium = MagicMock()
        fake_modules = {
            "tether_premium": mock_tether_premium,
            "tether_premium.register": mock_register,
        }

        with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=True)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}), \
             patch.dict(sys.modules, fake_modules):

            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("do a task", sent.append, None, TEST_USER_ID)

        mock_premium_handler.assert_awaited_once()
        assert "Premium reply" in sent
        # No stub/upgrade notice for paid user
        assert not any(
            "1.0" in s or "free" in s.lower() or "not yet wired" in s
            for s in sent
        ), f"Paid user must not see 1.0/free/stub notices. Got: {sent}"

    @pytest.mark.asyncio
    async def test_subscription_failure_falls_back_gracefully(self):
        """DB error on subscription check → treat as free, fall back to 1.0, no crash."""
        sent = []

        with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(side_effect=RuntimeError("DB down"))):

            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("do a task", sent.append, None, TEST_USER_ID)

        assert "1.0-response" in sent

    @pytest.mark.asyncio
    async def test_premium_import_error_falls_back_gracefully(self):
        """If tether_premium is not installed, paid user still gets 1.0 fallback."""
        sent = []

        with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=True)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}):

            # Simulate premium package absent
            import sys
            fake_modules = {
                "tether_premium": None,
                "tether_premium.register": None,
            }
            with patch.dict(sys.modules, fake_modules):
                from bot.agent_dispatch import _dispatch_v25
                await _dispatch_v25("do a task", sent.append, None, TEST_USER_ID)

        # Should have fallen back to 1.0, not crashed
        assert "1.0-response" in sent


# ---------------------------------------------------------------------------
# dispatch_message() routing
# ---------------------------------------------------------------------------

class TestDispatchMessageRouting:
    @pytest.mark.asyncio
    async def test_v25_routes_to_dispatch_v25_function(self):
        """dispatch_message('tether-agent-2.5') calls _dispatch_v25, not the generic stub."""
        sent = []

        with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0), \
             patch("bot.agent_dispatch._dispatch_v25", AsyncMock()) as mock_v25:

            from bot.agent_dispatch import dispatch_message
            await dispatch_message(
                "tether-agent-2.5", "hello",
                send_fn=sent.append, pool=None, user_id=TEST_USER_ID,
            )

        mock_v25.assert_awaited_once()
        # Generic "not yet wired" stub must NOT appear
        assert not any("not yet wired" in s for s in sent)

    @pytest.mark.asyncio
    async def test_v20_still_uses_stub(self):
        """tether-agent-2.0 still hits the stub (not owned by M4)."""
        sent = []

        with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0):
            from bot.agent_dispatch import dispatch_message
            await dispatch_message(
                "tether-agent-2.0", "hello",
                send_fn=sent.append, pool=None, user_id=TEST_USER_ID,
            )

        assert any("not yet wired" in s or "2.0" in s for s in sent)
