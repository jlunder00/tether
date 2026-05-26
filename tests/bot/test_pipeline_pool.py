"""Tests for pool-manager integration in the 2.5 pipeline.

Covers three behaviors:
  1. PipelineBackend.complete() uses pool_client.acquire/query_stream/release
     when pool_client + user_id are provided, instead of inline SDK spawn.
  2. _dispatch_v25 calls vault.materialize (sets _llm_env_extras) before
     invoking the premium handler.
  3. _dispatch_v25 passes pool_client + user_id kwargs into the premium
     handler call so LLMRouter can plumb them to PipelineBackend.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-for-tests")

TEST_USER_ID = "00000000-0000-0000-0000-000000000099"
FAKE_OAUTH_TOKEN = "test-oauth-token-abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(token: str = FAKE_OAUTH_TOKEN, raise_on_materialize: bool = False):
    """Build a mock vault whose materialize() yields CLAUDE_CODE_OAUTH_TOKEN."""
    import contextlib

    vault = MagicMock()

    @contextlib.asynccontextmanager
    async def _materialize(user_id: str):
        if raise_on_materialize:
            raise ValueError("no credentials")
        yield {"CLAUDE_CODE_OAUTH_TOKEN": token}

    @contextlib.asynccontextmanager
    async def _with_lock(user_id: str):
        yield

    vault.materialize = _materialize
    vault.with_lock = _with_lock
    return vault


def _make_pool_client(handle_id: str = "handle-abc", events: list | None = None):
    """Build a mock PoolClient that yields fake SSE events then completes."""
    pool_client = MagicMock()

    async def _acquire(user_id, options_hash, options, timeout_seconds=None):
        return handle_id

    async def _release(hid, *, reusable=False):
        pass

    async def _query_stream(hid, prompt, session_id="default"):
        for event in (events or []):
            yield event
        # Final text event
        yield {"type": "result", "result": "Pool response text", "subtype": "success"}

    pool_client.acquire = AsyncMock(side_effect=_acquire)
    pool_client.release = AsyncMock(side_effect=_release)
    pool_client.query_stream = _query_stream
    return pool_client


def _make_conn_ctx(is_paid: bool = True):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Fix 1 — _dispatch_v25 sets _llm_env_extras via vault.materialize
# ---------------------------------------------------------------------------

class TestDispatchV25VaultMaterialize:
    @pytest.mark.asyncio
    async def test_vault_materialize_called_for_paid_user(self):
        """vault.materialize(user_id) must be called before the premium handler runs."""
        import sys

        materialized_user_ids: list[str] = []
        import contextlib

        vault = MagicMock()

        @contextlib.asynccontextmanager
        async def _tracking_materialize(uid: str):
            materialized_user_ids.append(uid)
            yield {"CLAUDE_CODE_OAUTH_TOKEN": "token"}

        @contextlib.asynccontextmanager
        async def _with_lock(uid: str):
            yield

        vault.materialize = _tracking_materialize
        vault.with_lock = _with_lock

        mock_handler = AsyncMock(return_value=None)
        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(return_value=mock_handler)

        with patch("bot.agent_dispatch.handle_message", new=AsyncMock()), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=True)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}), \
             patch.dict(sys.modules, {
                 "tether_premium": MagicMock(),
                 "tether_premium.register": mock_register,
             }):
            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("hello", lambda x: None, None, TEST_USER_ID, vault=vault)

        assert TEST_USER_ID in materialized_user_ids, (
            "_dispatch_v25 must call vault.materialize(user_id) for paid users"
        )

    @pytest.mark.asyncio
    async def test_llm_env_extras_set_during_premium_handler_call(self):
        """_llm_env_extras ContextVar must be set with OAuth token while handler runs."""
        import sys
        from bot.llm import _llm_env_extras

        captured_extras: list = []

        async def _capturing_handler(*args, **kwargs):
            # Read the contextvar value while the handler is executing
            captured_extras.append(_llm_env_extras.get())
            return None

        vault = _make_vault(token="my-oauth-token")

        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(return_value=_capturing_handler)

        with patch("bot.agent_dispatch.handle_message", new=AsyncMock()), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=True)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}), \
             patch.dict(sys.modules, {
                 "tether_premium": MagicMock(),
                 "tether_premium.register": mock_register,
             }):
            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("hello", lambda x: None, None, TEST_USER_ID, vault=vault)

        assert len(captured_extras) == 1
        assert captured_extras[0] is not None, "_llm_env_extras must be set during handler"
        assert captured_extras[0].get("CLAUDE_CODE_OAUTH_TOKEN") == "my-oauth-token"

    @pytest.mark.asyncio
    async def test_llm_env_extras_cleared_after_handler_returns(self):
        """_llm_env_extras must be reset to None after the premium handler completes."""
        import sys
        from bot.llm import _llm_env_extras

        vault = _make_vault()

        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(
            return_value=AsyncMock(return_value=None)
        )

        with patch("bot.agent_dispatch.handle_message", new=AsyncMock()), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=True)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}), \
             patch.dict(sys.modules, {
                 "tether_premium": MagicMock(),
                 "tether_premium.register": mock_register,
             }):
            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("hello", lambda x: None, None, TEST_USER_ID, vault=vault)

        # After the call, the contextvar must be back to None (reset)
        assert _llm_env_extras.get() is None, (
            "_llm_env_extras must be reset after handler completes"
        )

    @pytest.mark.asyncio
    async def test_vault_missing_falls_back_gracefully(self):
        """No vault → no crash, no env set; falls back to 1.0 or runs premium without env."""
        import sys

        sent = []

        async def _fake_1_0(text, send_fn, pool, user_id, vault=None, status_fn=None):
            send_fn("1.0-response")

        with patch("bot.agent_dispatch.handle_message", new=_fake_1_0), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx(is_paid=False)), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=False)):
            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("hello", sent.append, None, TEST_USER_ID, vault=None)

        # Free user falls back to 1.0 regardless of vault
        assert "1.0-response" in sent


# ---------------------------------------------------------------------------
# Fix 1 (cont.) — _dispatch_v25 passes pool_client + user_id to handler
# ---------------------------------------------------------------------------

class TestDispatchV25PassesPoolClient:
    @pytest.mark.asyncio
    async def test_pool_client_passed_as_kwarg_to_premium_handler(self):
        """_dispatch_v25 must pass pool_client kwarg to the premium handler."""
        import sys

        received_kwargs: list[dict] = []

        async def _capturing_handler(*args, **kwargs):
            received_kwargs.append(kwargs)
            return None

        vault = _make_vault()
        mock_pool_client = MagicMock()

        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(return_value=_capturing_handler)

        with patch("bot.agent_dispatch.handle_message", new=AsyncMock()), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=True)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}), \
             patch.dict(sys.modules, {
                 "tether_premium": MagicMock(),
                 "tether_premium.register": mock_register,
             }):
            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25(
                "hello", lambda x: None, None, TEST_USER_ID,
                vault=vault, pool_client=mock_pool_client,
            )

        assert len(received_kwargs) == 1
        assert "pool_client" in received_kwargs[0], (
            "_dispatch_v25 must pass pool_client= to the premium handler"
        )
        assert received_kwargs[0]["pool_client"] is mock_pool_client

    @pytest.mark.asyncio
    async def test_dispatch_v25_creates_pool_client_from_config_if_not_passed(self):
        """When pool_client is not passed, _dispatch_v25 creates one from config."""
        import sys

        received_pool_clients: list = []

        async def _capturing_handler(*args, **kwargs):
            received_pool_clients.append(kwargs.get("pool_client"))
            return None

        vault = _make_vault()
        mock_created_client = MagicMock()

        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(return_value=_capturing_handler)

        with patch("bot.agent_dispatch.handle_message", new=AsyncMock()), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=True)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}), \
             patch("agent_pool_manager.client.from_config",
                   return_value=mock_created_client), \
             patch.dict(sys.modules, {
                 "tether_premium": MagicMock(),
                 "tether_premium.register": mock_register,
             }):
            from bot.agent_dispatch import _dispatch_v25
            # No pool_client kwarg — must auto-create
            await _dispatch_v25("hello", lambda x: None, None, TEST_USER_ID, vault=vault)

        assert len(received_pool_clients) == 1
        assert received_pool_clients[0] is not None, (
            "_dispatch_v25 must create a pool_client from config when none is provided"
        )


# ---------------------------------------------------------------------------
# Fix 3 — PipelineBackend uses pool when pool_client + user_id are provided
# ---------------------------------------------------------------------------

class TestPipelineBackendPoolAcquire:
    @pytest.mark.asyncio
    async def test_pool_acquire_called_with_correct_args(self):
        """When pool_client is present, complete() calls acquire with user_id + options_hash."""
        from bot.llm import PipelineBackend, LLMResponse

        pool_client = _make_pool_client()
        backend = PipelineBackend(pool_client=pool_client, user_id=TEST_USER_ID)

        result = await backend.complete(
            messages=[{"role": "user", "content": "test prompt"}],
            system="You are a helpful assistant.",
            model="claude-haiku-4-5-20251001",
        )

        pool_client.acquire.assert_awaited_once()
        acquire_call = pool_client.acquire.await_args
        # acquire(user_id, options_hash, options)
        assert acquire_call.args[0] == TEST_USER_ID, "acquire first arg must be user_id"
        assert isinstance(acquire_call.args[1], str), "acquire second arg must be options_hash string"
        assert isinstance(acquire_call.args[2], dict), "acquire third arg must be options dict"
        options = acquire_call.args[2]
        assert "model" in options
        assert options.get("permission_mode") == "bypassPermissions"

    @pytest.mark.asyncio
    async def test_pool_env_contains_oauth_token_from_llm_env_extras(self):
        """Options passed to acquire must include CLAUDE_CODE_OAUTH_TOKEN from _llm_env_extras."""
        from bot.llm import PipelineBackend, _llm_env_extras

        pool_client = _make_pool_client()
        backend = PipelineBackend(pool_client=pool_client, user_id=TEST_USER_ID)

        token = _llm_env_extras.set({"CLAUDE_CODE_OAUTH_TOKEN": "my-test-token"})
        try:
            await backend.complete(
                messages=[{"role": "user", "content": "test"}],
                system="sys",
                model="claude-haiku-4-5-20251001",
            )
        finally:
            _llm_env_extras.reset(token)

        acquire_call = pool_client.acquire.await_args
        options = acquire_call.args[2]
        assert options.get("env", {}).get("CLAUDE_CODE_OAUTH_TOKEN") == "my-test-token"

    @pytest.mark.asyncio
    async def test_pool_release_called_with_reusable_true(self):
        """After query_stream completes, release(handle_id, reusable=True) must be called."""
        from bot.llm import PipelineBackend

        handle_id = "test-handle-xyz"
        pool_client = _make_pool_client(handle_id=handle_id)
        backend = PipelineBackend(pool_client=pool_client, user_id=TEST_USER_ID)

        await backend.complete(
            messages=[{"role": "user", "content": "hello"}],
            system="sys",
            model="claude-haiku-4-5-20251001",
        )

        pool_client.release.assert_awaited_once_with(handle_id, reusable=True)

    @pytest.mark.asyncio
    async def test_options_hash_is_stable_across_identical_options(self):
        """The same options dict must always produce the same hash (no PYTHONHASHSEED drift)."""
        from bot.llm import PipelineBackend

        acquired_hashes: list[str] = []

        class _HashCapture(MagicMock):
            async def acquire(self, user_id, options_hash, options, timeout_seconds=None):
                acquired_hashes.append(options_hash)
                return "handle"

            async def release(self, hid, *, reusable=False):
                pass

            async def query_stream(self, hid, prompt, session_id="default"):
                yield {"type": "result", "result": "text", "subtype": "success"}

        pc = _HashCapture()
        backend = PipelineBackend(pool_client=pc, user_id=TEST_USER_ID)

        for _ in range(3):
            await backend.complete(
                messages=[{"role": "user", "content": "same prompt"}],
                system="same sys",
                model="claude-haiku-4-5-20251001",
            )

        assert len(set(acquired_hashes)) == 1, (
            "Options hash must be deterministic — same options must produce same hash"
        )

    @pytest.mark.asyncio
    async def test_pool_release_called_even_on_query_error(self):
        """release() must be called in a finally block even if query_stream raises.

        When query_stream fails, _complete_via_pool's finally block must still call
        release before the error propagates to the caller.  There is no inline fallback —
        the error propagates as-is so callers can detect pool failures explicitly.
        """
        from bot.llm import PipelineBackend

        pool_client = MagicMock()
        pool_client.acquire = AsyncMock(return_value="handle-err")
        pool_client.release = AsyncMock()

        async def _failing_stream(hid, prompt, session_id="default"):
            raise RuntimeError("pool query failed")
            yield  # make it a true async generator

        pool_client.query_stream = _failing_stream

        backend = PipelineBackend(pool_client=pool_client, user_id=TEST_USER_ID)

        # Error must propagate — no inline fallback
        with pytest.raises(RuntimeError, match="pool query failed"):
            await backend.complete(
                messages=[{"role": "user", "content": "test"}],
                system="sys",
                model="claude-haiku-4-5-20251001",
            )

        # release must still be called despite the stream error (via finally block in _complete_via_pool)
        pool_client.release.assert_awaited_once()

    def test_pipeline_backend_without_pool_client_is_pool_unaware(self):
        """PipelineBackend() with no args must not have pool_client or user_id set."""
        from bot.llm import PipelineBackend

        backend = PipelineBackend()

        # Without pool args, backend falls back to the inline SDK path.
        # The pool_client attribute must be None (or absent) — not accidentally wired.
        pool_client_val = getattr(backend, "_pool_client", None)
        user_id_val = getattr(backend, "_user_id", None)
        assert pool_client_val is None, (
            "PipelineBackend() without args must have no pool_client"
        )
        assert user_id_val is None, (
            "PipelineBackend() without args must have no user_id"
        )


# ---------------------------------------------------------------------------
# Code-review findings (post-PR fixes)
# ---------------------------------------------------------------------------

class TestCodeReviewFindings:
    """Tests for the 6 code-review findings from the pipeline-pool PR.

    Each test is written to FAIL before the fix is applied, confirming
    the fix is actually necessary (TDD red → green).
    """

    # Fix 3 — release reusable=False on error
    @pytest.mark.asyncio
    async def test_pool_release_reusable_false_on_query_error(self):
        """release must be called with reusable=False when query_stream raises.

        Previously reusable=True was unconditional — poisoned handles were
        returned to the pool and given to the next request.  The finally block in
        _complete_via_pool calls release(reusable=False) before the error propagates
        to the caller.  There is no inline fallback — the error surfaces as-is.
        """
        from bot.llm import PipelineBackend

        pool_client = MagicMock()
        pool_client.acquire = AsyncMock(return_value="handle-err")
        pool_client.release = AsyncMock()

        async def _failing_stream(hid, prompt, session_id="default"):
            raise RuntimeError("stream error")
            yield  # make it a true async generator

        pool_client.query_stream = _failing_stream

        backend = PipelineBackend(pool_client=pool_client, user_id=TEST_USER_ID)

        # Error must propagate — no inline fallback
        with pytest.raises(RuntimeError, match="stream error"):
            await backend.complete(
                messages=[{"role": "user", "content": "test"}],
                system="sys",
                model="claude-haiku-4-5-20251001",
            )

        pool_client.release.assert_awaited_once()
        _, kwargs = pool_client.release.await_args
        assert kwargs.get("reusable") is False, (
            "release must use reusable=False on error — poisoned handle must not re-enter pool"
        )

    # Fix 4 — no double-counted text
    @pytest.mark.asyncio
    async def test_no_double_text_from_result_and_assistant_events(self):
        """Text from result event must not be duplicated by assistant event text.

        Previously _complete_via_pool appended from BOTH assistant blocks and
        the result event, producing doubled output when both are emitted by the pool.
        """
        from bot.llm import PipelineBackend

        RESPONSE_TEXT = "the answer is forty-two"

        # Pool emits both an assistant text block AND a result event containing the same text.
        # After the fix only one source should be used.
        async def _double_emit_stream(hid, prompt, session_id="default"):
            yield {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": RESPONSE_TEXT}]},
            }
            yield {"type": "result", "result": RESPONSE_TEXT, "subtype": "success"}

        pool_client = MagicMock()
        pool_client.acquire = AsyncMock(return_value="handle-double")
        pool_client.release = AsyncMock()
        pool_client.query_stream = _double_emit_stream

        backend = PipelineBackend(pool_client=pool_client, user_id=TEST_USER_ID)
        result = await backend.complete(
            messages=[{"role": "user", "content": "question"}],
            system="sys",
            model="claude-haiku-4-5-20251001",
        )

        count = result.content.count(RESPONSE_TEXT)
        assert count == 1, (
            f"Text must appear exactly once in output, got {count} copies. "
            f"Content: {result.content!r}"
        )

    # Fix 5 — pool acquire failure raises (no silent fallback)
    @pytest.mark.asyncio
    async def test_pool_acquire_failure_raises(self):
        """When pool acquire() raises, PipelineBackend must propagate the error.

        Pool errors must be visible to the caller — silent fallback to inline spawn
        would hide pool health issues and re-introduce unbounded subprocess growth.
        Only when pool_client is None does PipelineBackend use inline.
        """
        from bot.llm import PipelineBackend

        pool_client = MagicMock()
        pool_client.acquire = AsyncMock(side_effect=RuntimeError("pool exhausted"))

        backend = PipelineBackend(pool_client=pool_client, user_id=TEST_USER_ID)

        # _complete_inline must NOT be called — verify by making it raise a distinct error
        async def _must_not_be_called(*args, **kwargs):
            raise AssertionError("_complete_inline must not be called when pool_client is set")

        with patch.object(backend, "_complete_inline", side_effect=_must_not_be_called):
            with pytest.raises(RuntimeError, match="pool exhausted"):
                await backend.complete(
                    messages=[{"role": "user", "content": "test"}],
                    system="sys",
                    model="claude-haiku-4-5-20251001",
                )

    # Fix 1 — _llm_user_id contextvar overrides frozen self._user_id
    @pytest.mark.asyncio
    async def test_llm_user_id_contextvar_overrides_stored_user_id(self):
        """_llm_user_id contextvar at call time must take precedence over self._user_id.

        This is the singleton fix: LLMRouter/PipelineBackend are created once (singleton)
        with the first caller's user_id baked in.  The contextvar ensures every subsequent
        request uses the *current* user_id at call time instead of the frozen one.
        """
        from bot.llm import PipelineBackend, _llm_user_id

        acquired_user_ids: list[str] = []

        pool_client = MagicMock()

        async def _acquire(user_id, options_hash, options, timeout_seconds=None):
            acquired_user_ids.append(user_id)
            return "handle"

        async def _query_stream(hid, prompt, session_id="default"):
            yield {"type": "result", "result": "text", "subtype": "success"}

        pool_client.acquire = AsyncMock(side_effect=_acquire)
        pool_client.release = AsyncMock()
        pool_client.query_stream = _query_stream

        # Backend created (as if singleton first-call) with user-A
        backend = PipelineBackend(pool_client=pool_client, user_id="user-id-A")

        # Simulate a different request: contextvar says user-B
        token = _llm_user_id.set("user-id-B")
        try:
            await backend.complete(
                messages=[{"role": "user", "content": "test"}],
                system="sys",
                model="claude-haiku-4-5-20251001",
            )
        finally:
            _llm_user_id.reset(token)

        assert acquired_user_ids == ["user-id-B"], (
            "acquire() must use _llm_user_id contextvar, not frozen self._user_id. "
            f"Got: {acquired_user_ids}"
        )

    # Fix 1 (dispatch side) — _dispatch_v25 sets _llm_user_id
    @pytest.mark.asyncio
    async def test_dispatch_v25_sets_llm_user_id_contextvar(self):
        """_dispatch_v25 must set _llm_user_id contextvar before invoking the premium handler."""
        import sys
        from bot.llm import _llm_user_id

        captured: list = []

        async def _capturing_handler(*args, **kwargs):
            captured.append(_llm_user_id.get())
            return None

        vault = _make_vault()
        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(return_value=_capturing_handler)

        with patch("bot.agent_dispatch.handle_message", new=AsyncMock()), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=True)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}), \
             patch.dict(sys.modules, {
                 "tether_premium": MagicMock(),
                 "tether_premium.register": mock_register,
             }):
            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("hello", lambda x: None, None, TEST_USER_ID, vault=vault)

        assert captured == [TEST_USER_ID], (
            f"_dispatch_v25 must set _llm_user_id={TEST_USER_ID!r} before calling handler. "
            f"Got: {captured}"
        )

    # Fix 2 — ValueError from handler must not trigger double-invocation
    @pytest.mark.asyncio
    async def test_handler_value_error_not_double_invoked(self):
        """ValueError raised by the premium handler must not trigger a second invocation.

        Previously, ValueError raised inside the vault.materialize block was caught
        by the same except ValueError clause that handles 'no vault credentials',
        causing the handler to be called a second time.
        """
        import sys

        invocations: list[int] = []

        async def _raising_handler(*args, **kwargs):
            invocations.append(len(invocations) + 1)
            raise ValueError("handler internal error")

        vault = _make_vault()  # vault materializes fine — not the source of ValueError
        mock_register = MagicMock()
        mock_register.get_premium_handler = MagicMock(return_value=_raising_handler)

        sent = []

        async def _fake_1_0(text, send_fn, pool, user_id, vault=None, status_fn=None):
            send_fn("1.0-response")

        with patch("bot.agent_dispatch.handle_message", new=_fake_1_0), \
             patch("db.postgres.get_conn", return_value=_make_conn_ctx()), \
             patch("db.pg_queries.subscriptions.get_user_is_paid",
                   new=AsyncMock(return_value=True)), \
             patch("db.pg_queries.get_anchors", new=AsyncMock(return_value=[])), \
             patch("bot.handler_utils.get_current_anchor", return_value={}), \
             patch.dict(sys.modules, {
                 "tether_premium": MagicMock(),
                 "tether_premium.register": mock_register,
             }):
            from bot.agent_dispatch import _dispatch_v25
            await _dispatch_v25("hello", sent.append, None, TEST_USER_ID, vault=vault)

        assert invocations == [1], (
            f"Handler must be invoked exactly once; invocation count: {invocations}"
        )
        # 1.0 fallback should have run (handler raised before sending anything)
        assert "1.0-response" in sent
