"""Tests for tether-agent-2.5 dispatch path in agent_dispatch.py.

M4 wires a real 2.5 path: paid users get the premium session handler;
free users receive an upgrade notice and fall back to tether-agent-1.0.

M4 hotfix: admin users bypass the subscription check entirely and are
routed directly to the premium path regardless of subscription row.

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

    @pytest.mark.asyncio
    async def test_admin_user_bypasses_subscription_check_and_gets_premium(self):
        """Admin user with no subscription row must reach premium handler, not 1.0 fallback.

        is_admin=True must short-circuit the paid check entirely — no subscription
        row is required.  get_user_is_paid returns False (simulates no row), but
        the admin flag overrides and routes to the premium path.
        """
        import sys
        sent = []
        mock_premium_handler = AsyncMock(return_value="Premium reply for admin")

        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(return_value=mock_premium_handler)
        mock_tether_premium = MagicMock()
        fake_modules = {
            "tether_premium": mock_tether_premium,
            "tether_premium.register": mock_register,
        }

        with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx(is_paid_return=False)), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=False)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}), \
             patch.dict(sys.modules, fake_modules):

            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("do a task", sent.append, None, TEST_USER_ID, is_admin=True)

        mock_premium_handler.assert_awaited_once()
        assert "Premium reply for admin" in sent
        # No upgrade/free-plan notice for admins
        assert not any(
            "free plan" in s.lower() or "pro plan" in s.lower()
            for s in sent
        ), f"Admin must not see free-plan upgrade notice. Got: {sent}"
        # Must NOT have fallen back to 1.0
        assert "1.0-response" not in sent, "Admin must not fall back to 1.0"

    @pytest.mark.asyncio
    async def test_admin_flag_forwarded_from_dispatch_message(self):
        """dispatch_message passes is_admin through to _dispatch_v25."""
        with patch("bot.agent_dispatch.handle_message", new=_fake_handle_1_0), \
             patch("bot.agent_dispatch._dispatch_v25", AsyncMock()) as mock_v25:

            from bot.agent_dispatch import dispatch_message
            await dispatch_message(
                "tether-agent-2.5", "hello",
                send_fn=lambda m: None, pool=None, user_id=TEST_USER_ID,
                is_admin=True,
            )

        _args, kwargs = mock_v25.call_args
        assert kwargs.get("is_admin") is True, \
            f"_dispatch_v25 must receive is_admin=True, got call_args={mock_v25.call_args}"


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


# ---------------------------------------------------------------------------
# _SendTracker / double-send guard
# ---------------------------------------------------------------------------

class TestDoubleSendGuard:
    """Tests for the _SendTracker double-send protection.

    When a premium handler streams output via send_fn and then raises an
    exception, the 1.0 fallback path must NOT run (no double-send).
    When the premium handler raises without ever calling send_fn, the 1.0
    fallback MUST run so the user always gets a response.
    """

    @pytest.mark.asyncio
    async def test_premium_streams_then_raises_skips_fallback(self):
        """Premium handler streams partial output then raises → exactly one message, no 1.0 fallback.

        This is the core double-send regression: previously, the exception
        handler fell through to handle_message even after premium had already
        called send_fn, producing spliced output (premium partial + 1.0 response).
        """
        import sys
        sent = []

        async def _streaming_then_crashing(
            text, pool, user_id, anchors, current_anchor, *,
            send_fn, status_fn=None, pool_client=None
        ):
            send_fn("premium-partial")  # streams something first
            raise RuntimeError("handler crashed mid-stream")

        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(return_value=_streaming_then_crashing)
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

        assert "premium-partial" in sent, f"Premium output must be delivered. Got: {sent}"
        assert "1.0-response" not in sent, (
            f"Double-send: handle_message ran after premium already streamed. Got: {sent}"
        )
        assert sent.count("premium-partial") == 1, \
            f"Premium output must appear exactly once. Got: {sent}"

    @pytest.mark.asyncio
    async def test_premium_raises_without_streaming_still_runs_fallback(self):
        """Premium handler raises before sending anything → 1.0 fallback runs normally.

        This is the regression guard: the double-send fix must NOT suppress
        the fallback when premium never actually sent any output.
        """
        import sys
        sent = []

        async def _crashing_immediately(
            text, pool, user_id, anchors, current_anchor, *,
            send_fn, status_fn=None, pool_client=None
        ):
            raise RuntimeError("handler failed before sending anything")

        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(return_value=_crashing_immediately)
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

        assert "1.0-response" in sent, \
            f"Fallback must run when premium never sent output. Got: {sent}"
        assert "premium-partial" not in sent

