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
         patch("bot.message_handler.load_config", side_effect=FileNotFoundError):
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
# get_model
# ---------------------------------------------------------------------------

def test_get_model_returns_config_value_when_present():
    from bot.message_handler import get_model
    with patch("bot.message_handler.load_config", return_value={"models": {"orchestrator": "custom-model"}}):
        assert get_model("orchestrator") == "custom-model"


def test_get_model_falls_back_to_default_when_key_missing():
    from bot.message_handler import get_model, _MODEL_DEFAULTS
    with patch("bot.message_handler.load_config", return_value={"models": {}}):
        assert get_model("orchestrator") == _MODEL_DEFAULTS["orchestrator"]


def test_get_model_falls_back_when_config_missing():
    from bot.message_handler import get_model, _MODEL_DEFAULTS
    with patch("bot.message_handler.load_config", side_effect=FileNotFoundError):
        assert get_model("meta_eval") == _MODEL_DEFAULTS["meta_eval"]


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
