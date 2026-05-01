"""Tests for bot/llm.py — LLM abstraction layer."""
import pytest


# ---------------------------------------------------------------------------
# Dataclass structure
# ---------------------------------------------------------------------------

class TestLLMResponseDataclass:
    def test_can_be_constructed(self):
        from bot.llm import LLMResponse
        r = LLMResponse(
            content="hello",
            tool_calls=[],
            stop_reason="end_turn",
            input_tokens=10,
            output_tokens=5,
        )
        assert r.content == "hello"
        assert r.stop_reason == "end_turn"
        assert r.input_tokens == 10
        assert r.output_tokens == 5


class TestToolCallDataclass:
    def test_can_be_constructed(self):
        from bot.llm import ToolCall
        tc = ToolCall(id="call_1", name="get_plan", input={"date": "today"})
        assert tc.id == "call_1"
        assert tc.name == "get_plan"
        assert tc.input == {"date": "today"}


# ---------------------------------------------------------------------------
# PipelineBackend
# ---------------------------------------------------------------------------

class TestPipelineBackend:
    def test_is_always_available(self):
        from bot.llm import PipelineBackend
        b = PipelineBackend()
        assert b.is_available() is True

    def test_complete_returns_llm_response(self):
        from bot.llm import PipelineBackend, LLMResponse
        from claude_agent_sdk import AssistantMessage, TextBlock
        from unittest.mock import patch
        import asyncio

        async def _fake_query(*, prompt, options=None, transport=None):
            msg = AssistantMessage(
                content=[TextBlock(text="hello from claude")],
                model="claude-sonnet-4-6",
            )
            yield msg

        b = PipelineBackend()
        with patch("claude_agent_sdk.query", side_effect=_fake_query):
            resp = asyncio.run(b.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="you are helpful",
                model="claude-haiku-4-5-20251001",
            ))
        assert isinstance(resp, LLMResponse)
        assert resp.content == "hello from claude"
        assert resp.tool_calls == []
        assert resp.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# PipelineBackend — SDK migration
# ---------------------------------------------------------------------------

class TestPipelineBackendSDKMigration:
    """PipelineBackend now uses claude_agent_sdk.query(), not subprocess."""

    @pytest.mark.asyncio
    async def test_complete_uses_sdk_not_subprocess(self, monkeypatch):
        from bot.llm import PipelineBackend, LLMResponse
        from claude_agent_sdk import AssistantMessage, TextBlock
        from unittest.mock import patch
        import subprocess

        async def _fake_query(*, prompt, options=None, transport=None):
            msg = AssistantMessage(
                content=[TextBlock(text="sdk reply")],
                model="claude-sonnet-4-6",
            )
            yield msg

        subprocess_called = []
        original_run = subprocess.run
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess_called.append(True) or original_run(*a, **kw)
        )

        b = PipelineBackend()
        with patch("claude_agent_sdk.query", side_effect=_fake_query):
            resp = await b.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="you are helpful",
                model="claude-haiku-4-5-20251001",
            )
        assert resp.content == "sdk reply"
        assert not subprocess_called

    @pytest.mark.asyncio
    async def test_complete_passes_env_extras_in_env(self):
        from bot.llm import PipelineBackend, _llm_env_extras
        from claude_agent_sdk import AssistantMessage, TextBlock, ClaudeAgentOptions
        from unittest.mock import patch

        captured: list[ClaudeAgentOptions] = []

        async def _fake_query(*, prompt, options=None, transport=None):
            captured.append(options)
            msg = AssistantMessage(
                content=[TextBlock(text="ok")],
                model="claude-sonnet-4-6",
            )
            yield msg

        extras = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-pipeline"}
        token = _llm_env_extras.set(extras)
        try:
            b = PipelineBackend()
            with patch("claude_agent_sdk.query", side_effect=_fake_query):
                await b.complete(
                    messages=[{"role": "user", "content": "hi"}],
                    system="sys",
                    model="claude-haiku-4-5-20251001",
                )
        finally:
            _llm_env_extras.reset(token)

        assert len(captured) == 1
        assert captured[0].env.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-pipeline"


# ---------------------------------------------------------------------------
# AnthropicBackend
# ---------------------------------------------------------------------------

class TestAnthropicBackend:
    def test_unavailable_when_no_token_and_no_api_key(self, monkeypatch):
        from bot.llm import AnthropicBackend, _llm_env_extras
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        token = _llm_env_extras.set(None)
        try:
            b = AnthropicBackend()
            assert b.is_available() is False
        finally:
            _llm_env_extras.reset(token)

    def test_available_when_api_key_set(self, monkeypatch):
        from bot.llm import AnthropicBackend, _llm_env_extras
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        token = _llm_env_extras.set(None)
        try:
            b = AnthropicBackend()
            assert b.is_available() is True
        finally:
            _llm_env_extras.reset(token)

    def test_available_when_valid_oauth_token_in_env_extras(self, monkeypatch):
        from bot.llm import AnthropicBackend, _llm_env_extras
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        token = _llm_env_extras.set({"CLAUDE_CODE_OAUTH_TOKEN": "fake-tok"})
        try:
            b = AnthropicBackend()
            assert b.is_available() is True
        finally:
            _llm_env_extras.reset(token)

    def test_get_oauth_token_does_not_use_bot_oauth_module(self, monkeypatch):
        """_get_oauth_token must read _llm_env_extras, not import bot.oauth."""
        import sys
        from bot.llm import AnthropicBackend, _llm_env_extras

        # Poison bot.oauth in sys.modules so any import attempt raises
        sys.modules["bot.oauth"] = None  # type: ignore[assignment]
        try:
            token = _llm_env_extras.set({"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test"})
            try:
                b = AnthropicBackend()
                result = b._get_oauth_token()
                assert result == "sk-ant-test"
            finally:
                _llm_env_extras.reset(token)
        finally:
            sys.modules.pop("bot.oauth", None)

    def test_no_credentials_path_param(self):
        """AnthropicBackend() must not accept a credentials_path parameter."""
        from bot.llm import AnthropicBackend
        import inspect
        sig = inspect.signature(AnthropicBackend.__init__)
        assert "credentials_path" not in sig.parameters, (
            "credentials_path param must be removed from AnthropicBackend.__init__"
        )


# ---------------------------------------------------------------------------
# OpenAI / OpenRouter backends
# ---------------------------------------------------------------------------

class TestOpenAIBackend:
    def test_unavailable_without_api_key(self, monkeypatch):
        from bot.llm import OpenAIBackend
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        b = OpenAIBackend()
        assert b.is_available() is False

    def test_available_with_api_key(self, monkeypatch):
        from bot.llm import OpenAIBackend
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        b = OpenAIBackend()
        assert b.is_available() is True

    def test_available_with_explicit_key(self):
        from bot.llm import OpenAIBackend
        b = OpenAIBackend(api_key="sk-explicit")
        assert b.is_available() is True


class TestOpenRouterBackend:
    def test_unavailable_without_api_key(self, monkeypatch):
        from bot.llm import OpenRouterBackend
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        b = OpenRouterBackend()
        assert b.is_available() is False

    def test_available_with_api_key(self, monkeypatch):
        from bot.llm import OpenRouterBackend
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        b = OpenRouterBackend()
        assert b.is_available() is True


# ---------------------------------------------------------------------------
# AWSBedrockBackend
# ---------------------------------------------------------------------------

class TestAWSBedrockBackend:
    def test_available_with_ambient_credentials(self):
        import sys
        import unittest.mock as mock
        from bot.llm import AWSBedrockBackend

        class FakeCreds:
            def get_frozen_credentials(self):
                class C:
                    access_key = "AKIA"
                return C()

        class FakeSession:
            def get_credentials(self):
                return FakeCreds()

        fake_boto3 = mock.MagicMock()
        fake_boto3.Session.return_value = FakeSession()
        with mock.patch.dict(sys.modules, {"boto3": fake_boto3}):
            b = AWSBedrockBackend()
            assert b.is_available() is True

    def test_unavailable_without_credentials(self):
        import sys
        import unittest.mock as mock
        from bot.llm import AWSBedrockBackend

        class FakeSession:
            def get_credentials(self):
                return None

        fake_boto3 = mock.MagicMock()
        fake_boto3.Session.return_value = FakeSession()
        with mock.patch.dict(sys.modules, {"boto3": fake_boto3}):
            b = AWSBedrockBackend()
            assert b.is_available() is False


# TestLLMRouter moved to tether-premium

# ---------------------------------------------------------------------------

class TestToolSchemaAdapters:
    def test_to_anthropic_schema_is_identity(self):
        """Anthropic canonical schema should pass through unchanged."""
        from bot.llm_adapters import to_anthropic_schema
        tool = {
            "name": "get_plan",
            "description": "Get today's plan",
            "input_schema": {"type": "object", "properties": {"date": {"type": "string"}}},
        }
        result = to_anthropic_schema(tool)
        assert result == tool

    def test_to_openai_schema_converts_input_schema(self):
        """OpenAI uses 'parameters' instead of 'input_schema'."""
        from bot.llm_adapters import to_openai_schema
        tool = {
            "name": "get_plan",
            "description": "Get today's plan",
            "input_schema": {"type": "object", "properties": {"date": {"type": "string"}}},
        }
        result = to_openai_schema(tool)
        assert result["type"] == "function"
        assert result["function"]["name"] == "get_plan"
        assert result["function"]["parameters"] == tool["input_schema"]
        assert "input_schema" not in result["function"]

    def test_to_bedrock_schema_uses_toolSpec(self):
        """Bedrock converse API uses 'toolSpec' wrapper."""
        from bot.llm_adapters import to_bedrock_schema
        tool = {
            "name": "get_plan",
            "description": "Get today's plan",
            "input_schema": {"type": "object", "properties": {}},
        }
        result = to_bedrock_schema(tool)
        assert "toolSpec" in result
        assert result["toolSpec"]["name"] == "get_plan"
        assert result["toolSpec"]["inputSchema"]["json"] == tool["input_schema"]
