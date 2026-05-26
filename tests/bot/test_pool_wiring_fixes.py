"""Tests for pool-wiring Fix 3 (tether repo).

Fix 3: PipelineBackend.complete() raises when the pool path fails —
       silent fallback to inline spawn is removed.

SAFETY: All tests patch _complete_inline to avoid real subprocess spawning.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPipelineBackendNoInlineFallback:
    """When pool_client is set and the pool path raises, the error must
    propagate to the caller.  _complete_inline must never be reached."""

    @pytest.mark.asyncio
    async def test_pool_error_propagates_not_swallowed(self):
        """Pool PoolClientError must propagate — not trigger inline spawn."""
        from bot.llm import PipelineBackend
        from agent_pool_manager.client import PoolClientError

        mock_pool = MagicMock()
        mock_pool.acquire = AsyncMock(side_effect=PoolClientError("pool exhausted"))

        backend = PipelineBackend(pool_client=mock_pool, user_id="user-123")

        # Patch _complete_inline so any call immediately fails the test with
        # a clear message, rather than timing out on a real subprocess spawn.
        async def _must_not_be_called(*args, **kwargs):
            raise AssertionError("_complete_inline must not be called when pool_client is set")

        with patch.object(backend, "_complete_inline", side_effect=_must_not_be_called):
            with pytest.raises(PoolClientError):
                await backend.complete(
                    messages=[{"role": "user", "content": "do work"}],
                    system="system",
                    model="claude-sonnet-4-6",
                )

    @pytest.mark.asyncio
    async def test_pool_runtime_error_propagates(self):
        """Generic pool RuntimeError also propagates without falling back."""
        from bot.llm import PipelineBackend

        mock_pool = MagicMock()
        mock_pool.acquire = AsyncMock(side_effect=RuntimeError("pool service down"))

        backend = PipelineBackend(pool_client=mock_pool, user_id="user-456")

        with patch.object(backend, "_complete_inline", new=AsyncMock()) as mock_inline:
            with pytest.raises(RuntimeError):
                await backend.complete(
                    messages=[{"role": "user", "content": "hi"}],
                    system="system",
                    model="claude-haiku-4-5-20251001",
                )
            mock_inline.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_pool_client_still_uses_inline(self):
        """Without pool_client, _complete_inline is still used (backward compat)."""
        from bot.llm import PipelineBackend, LLMResponse

        backend = PipelineBackend(pool_client=None, user_id=None)

        with patch.object(
            backend, "_complete_inline",
            new=AsyncMock(return_value="inline result"),
        ) as mock_inline:
            result = await backend.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="system",
                model="claude-haiku-4-5-20251001",
            )

        mock_inline.assert_called_once()
        assert isinstance(result, LLMResponse)
        assert result.content == "inline result"
