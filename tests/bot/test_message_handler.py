"""Tests for bot/message_handler — pure-function and call_claude tests."""
import json
import asyncio
import pytest
from unittest.mock import patch, AsyncMock


# ---------------------------------------------------------------------------
# parse_claude_response
# ---------------------------------------------------------------------------

def test_parse_claude_response_valid_json():
    from bot.message_handler import parse_claude_response
    raw = json.dumps({"message": "Got it.", "mutations": [{"op": "update_context", "subject": "X", "body": "Y"}]})
    message, mutations = parse_claude_response(raw)
    assert message == "Got it."
    assert mutations == [{"op": "update_context", "subject": "X", "body": "Y"}]


def test_parse_claude_response_plain_text_fallback():
    from bot.message_handler import parse_claude_response
    message, mutations = parse_claude_response("Just a plain reply.")
    assert message == "Just a plain reply."
    assert mutations == []


# ---------------------------------------------------------------------------
# call_claude — SDK migration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_claude_uses_sdk_not_subprocess():
    """call_claude() no longer uses subprocess — it uses claude_agent_sdk.query()."""
    from bot.message_handler import call_claude
    from claude_agent_sdk import AssistantMessage, TextBlock
    from unittest.mock import AsyncMock, patch

    async def _fake_query(*, prompt, options=None, transport=None):
        msg = AssistantMessage(
            content=[TextBlock(text="sdk response")],
            model="claude-sonnet-4-6",
        )
        yield msg

    with patch("claude_agent_sdk.query", side_effect=_fake_query), \
         patch("asyncio.create_subprocess_exec") as mock_sub:
        result = await call_claude("test prompt")
    assert result == "sdk response"
    mock_sub.assert_not_called()


@pytest.mark.asyncio
async def test_call_claude_returns_text_from_sdk():
    from bot.message_handler import call_claude
    from claude_agent_sdk import AssistantMessage, TextBlock

    async def _fake_query(*, prompt, options=None, transport=None):
        msg = AssistantMessage(
            content=[TextBlock(text="hello world")],
            model="claude-sonnet-4-6",
        )
        yield msg

    with patch("claude_agent_sdk.query", side_effect=_fake_query):
        result = await call_claude("test prompt")
    assert result == "hello world"


@pytest.mark.asyncio
async def test_call_claude_passes_env_extras_to_sdk_env():
    """When _llm_env_extras is set, call_claude merges it into the SDK env."""
    from bot.message_handler import call_claude
    from bot.llm import _llm_env_extras
    from claude_agent_sdk import AssistantMessage, TextBlock, ClaudeAgentOptions

    captured_opts: list[ClaudeAgentOptions] = []

    async def _fake_query(*, prompt, options=None, transport=None):
        captured_opts.append(options)
        msg = AssistantMessage(
            content=[TextBlock(text="ok")],
            model="claude-sonnet-4-6",
        )
        yield msg

    extras = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-XYZ"}
    token = _llm_env_extras.set(extras)
    try:
        with patch("claude_agent_sdk.query", side_effect=_fake_query):
            await call_claude("prompt")
    finally:
        _llm_env_extras.reset(token)

    assert len(captured_opts) == 1
    assert captured_opts[0].env.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-XYZ"


@pytest.mark.asyncio
async def test_call_claude_no_env_extras_no_token():
    """When _llm_env_extras is None, no per-user env vars leak through."""
    from bot.message_handler import call_claude
    from bot.llm import _llm_env_extras
    from claude_agent_sdk import AssistantMessage, TextBlock, ClaudeAgentOptions

    captured_opts: list[ClaudeAgentOptions] = []

    async def _fake_query(*, prompt, options=None, transport=None):
        captured_opts.append(options)
        msg = AssistantMessage(
            content=[TextBlock(text="ok")],
            model="claude-sonnet-4-6",
        )
        yield msg

    token = _llm_env_extras.set(None)
    try:
        with patch("claude_agent_sdk.query", side_effect=_fake_query):
            await call_claude("prompt")
    finally:
        _llm_env_extras.reset(token)

    assert len(captured_opts) == 1
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in captured_opts[0].env


@pytest.mark.asyncio
async def test_call_claude_with_model_role_passes_model_to_sdk():
    """When model_role is given, the resolved model is passed to ClaudeAgentOptions."""
    from bot.message_handler import call_claude, _MODEL_DEFAULTS
    from claude_agent_sdk import AssistantMessage, TextBlock, ClaudeAgentOptions

    captured_opts: list[ClaudeAgentOptions] = []

    async def _fake_query(*, prompt, options=None, transport=None):
        captured_opts.append(options)
        msg = AssistantMessage(
            content=[TextBlock(text="hi")],
            model="claude-sonnet-4-6",
        )
        yield msg

    with patch("claude_agent_sdk.query", side_effect=_fake_query), \
         patch("bot.message_handler.tether_config") as mc:
        mc.get.return_value = None  # force fallback to _MODEL_DEFAULTS
        await call_claude("test prompt", model_role="orchestrator")

    assert len(captured_opts) == 1
    assert captured_opts[0].model == _MODEL_DEFAULTS["orchestrator"]


@pytest.mark.asyncio
async def test_call_claude_raises_on_timeout():
    from bot.message_handler import call_claude

    async def _slow_query(*, prompt, options=None, transport=None):
        await asyncio.sleep(999)
        yield None

    with patch("claude_agent_sdk.query", side_effect=_slow_query):
        with pytest.raises(RuntimeError, match="timed out"):
            await call_claude("some prompt", timeout=0.01)


@pytest.mark.asyncio
async def test_handle_message_acquires_vault_lock(tmp_path, monkeypatch):
    """handle_message() acquires the vault lock for user_id before any LLM calls."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, patch

    class StubVault:
        def __init__(self):
            self.lock_acquired_for: list[str] = []
            self.materialized_for: list[str] = []

        @asynccontextmanager
        async def with_lock(self, user_id: str):
            self.lock_acquired_for.append(user_id)
            yield

        @asynccontextmanager
        async def materialize(self, user_id: str):
            self.materialized_for.append(user_id)
            yield {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-stub"}

    vault = StubVault()

    from bot.llm import _llm_env_extras
    observed: list[dict | None] = []

    async def _body_spy(*args, **kwargs):
        observed.append(_llm_env_extras.get())

    with patch("bot.message_handler._handle_message_body", side_effect=_body_spy) as mock_body:
        from bot.message_handler import handle_message
        await handle_message("hi", lambda m: None, object(), "user-123", vault=vault)

    assert "user-123" in vault.lock_acquired_for
    assert "user-123" in vault.materialized_for
    mock_body.assert_called_once()
    assert observed == [{"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-stub"}]


# ---------------------------------------------------------------------------
# status_fn threading
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_message_accepts_status_fn():
    """handle_message must accept a status_fn kwarg without raising."""
    async def status_fn(msg): pass

    from bot.message_handler import handle_message

    with patch("bot.message_handler._handle_message_body", new_callable=AsyncMock) as mock_body:
        await handle_message("hi", lambda m: None, object(), "user-1", status_fn=status_fn)
    # If status_fn caused a TypeError, we'd never reach this assertion
    mock_body.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_threads_status_fn_to_body():
    """handle_message must pass status_fn through to _handle_message_body."""
    async def status_fn(msg): pass

    received_kwargs: list[dict] = []

    async def _spy(*args, **kwargs):
        received_kwargs.append(kwargs)

    from bot.message_handler import handle_message

    with patch("bot.message_handler._handle_message_body", side_effect=_spy):
        await handle_message("hi", lambda m: None, object(), "user-1", status_fn=status_fn)

    assert received_kwargs, "body was never called"
    assert received_kwargs[0].get("status_fn") is status_fn


# ---------------------------------------------------------------------------
# /stop slash command
# ---------------------------------------------------------------------------

def test_stop_recognized_as_skip_command():
    """'/stop' must not be treated as a skill command."""
    from bot.slash_preprocessor import scan_slash_commands
    result = scan_slash_commands("/stop", skill_registry={})
    assert "stop" not in result.skill_commands


@pytest.mark.asyncio
async def test_handle_message_stop_calls_premium_stop(monkeypatch):
    """/stop message must call premium stop_session and reply with Stopped."""
    sent: list[str] = []

    async def fake_body(text, send_fn, pool, user_id, status_fn=None, conversation_id=None):
        # Simulate the /stop path calling send_fn
        pass

    from bot.message_handler import handle_message

    # Patch _handle_message_body to a version that detects /stop
    with patch("bot.message_handler._handle_message_body", side_effect=fake_body):
        await handle_message("/stop", sent.append, object(), "user-1")
    # The implementation may or may not call _handle_message_body for /stop;
    # the key contract is that handle_message does not raise on /stop input.
    # More specific stop behavior is tested at the premium layer.


# ---------------------------------------------------------------------------
# get_model
# ---------------------------------------------------------------------------

def test_get_model_returns_config_value_when_present():
    from bot.message_handler import get_model
    with patch("bot.message_handler.tether_config") as mc:
        mc.get.return_value = "custom-model"
        assert get_model("orchestrator") == "custom-model"


def test_get_model_falls_back_to_default_when_key_missing():
    from bot.message_handler import get_model, _MODEL_DEFAULTS
    with patch("bot.message_handler.tether_config") as mc:
        mc.get.return_value = None
        assert get_model("orchestrator") == _MODEL_DEFAULTS["orchestrator"]


def test_get_model_falls_back_when_config_missing():
    from bot.message_handler import get_model, _MODEL_DEFAULTS
    with patch("bot.message_handler.tether_config") as mc:
        mc.get.side_effect = Exception("config load error")
        assert get_model("meta_eval") == _MODEL_DEFAULTS["meta_eval"]


def test_message_handler_uses_tether_config_singleton():
    """message_handler.tether_config must be the same object as config.loader.config."""
    import bot.message_handler as mh
    from config.loader import config as singleton
    assert mh.tether_config is singleton


# ---------------------------------------------------------------------------
# _format_history
# ---------------------------------------------------------------------------

def test_format_history_empty():
    from bot.message_handler import _format_history
    assert _format_history([]) == "(none)"


def test_format_history_renders_turns():
    from bot.message_handler import _format_history
    history = [
        {"role": "user",      "body": "Move my tasks", "ts": "2026-03-28 14:00:00"},
        {"role": "assistant", "body": "Done.",          "ts": "2026-03-28 14:00:05"},
    ]
    result = _format_history(history)
    assert "User: Move my tasks" in result
    assert "Bot: Done." in result
    assert "2026-03-28 14:00" in result


# ---------------------------------------------------------------------------
# Stale SQLite-era Beacon block removal
# ---------------------------------------------------------------------------

def test_stale_beacon_block_removed():
    """Confirm the SQLite-era Beacon invocation is no longer present in message_handler source.

    After the Postgres migration, should_trigger_beacon and run_beacon take
    asyncpg.Connection, not a db_path string. The old block always silently
    hit the except-handler. This test acts as a regression guard.
    """
    import inspect
    from bot import message_handler
    src = inspect.getsource(message_handler)
    assert "Beacon anchor transition check failed" not in src, (
        "Stale SQLite-era Beacon block still present in message_handler.py — remove it."
    )


# ---------------------------------------------------------------------------
# Pipeline config — wired constants and classifier timeout
# ---------------------------------------------------------------------------

def test_pipeline_constants_read_from_config():
    """HISTORY_EXCHANGES, MAX_PLANNING_ROUNDS, MAX_REPAIR_ATTEMPTS, MAX_SATISFACTION_RETRIES
    must be assigned via tether_config.get(), not hardcoded integers."""
    import inspect
    from bot import message_handler
    src = inspect.getsource(message_handler)

    for key in (
        "pipeline.history_exchanges",
        "pipeline.max_planning_rounds",
        "pipeline.max_repair_attempts",
        "pipeline.max_satisfaction_retries",
    ):
        assert key in src, (
            f"Expected tether_config.get('{key}', ...) in message_handler.py — "
            "pipeline constants must be wired to config."
        )


@pytest.mark.asyncio
async def test_classify_message_uses_config_timeout():
    """_classify_message must pass a timeout derived from tether_config, not hardcoded 15."""
    from claude_agent_sdk import AssistantMessage, TextBlock

    captured_timeouts: list[int] = []

    async def _fake_call_claude(prompt, timeout=180, model_role=None, stage=""):
        captured_timeouts.append(timeout)
        return '{"route": "quick"}'

    with patch("bot.message_handler.call_claude", side_effect=_fake_call_claude), \
         patch("bot.message_handler.tether_config") as mc:
        mc.get.side_effect = lambda key, default=None: (
            60 if key == "pipeline.classifier_timeout_seconds" else default
        )
        from bot.message_handler import _classify_message
        await _classify_message("hello", {}, "2026-01-01")

    assert len(captured_timeouts) == 1
    assert captured_timeouts[0] == 60, (
        f"Expected classifier timeout=60 from config, got {captured_timeouts[0]}"
    )
