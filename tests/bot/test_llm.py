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
    async def test_complete_passes_creds_dir_in_env(self, tmp_path):
        from bot.llm import PipelineBackend, _llm_creds_dir
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

        creds_path = str(tmp_path / "mycreds")
        token = _llm_creds_dir.set(creds_path)
        try:
            b = PipelineBackend()
            with patch("claude_agent_sdk.query", side_effect=_fake_query):
                await b.complete(
                    messages=[{"role": "user", "content": "hi"}],
                    system="sys",
                    model="claude-haiku-4-5-20251001",
                )
        finally:
            _llm_creds_dir.reset(token)

        assert len(captured) == 1
        assert captured[0].env.get("CLAUDE_CONFIG_DIR") == creds_path


# ---------------------------------------------------------------------------
# AnthropicBackend
# ---------------------------------------------------------------------------

class TestAnthropicBackend:
    def test_unavailable_when_no_token_and_no_api_key(self, monkeypatch, tmp_path):
        from bot.llm import AnthropicBackend
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        b = AnthropicBackend(credentials_path=str(tmp_path / "nonexistent.json"))
        assert b.is_available() is False

    def test_available_when_api_key_set(self, monkeypatch, tmp_path):
        from bot.llm import AnthropicBackend
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        b = AnthropicBackend(credentials_path=str(tmp_path / "nonexistent.json"))
        assert b.is_available() is True

    def test_available_when_valid_credentials_file_exists(self, tmp_path, monkeypatch):
        import json, time
        from bot.llm import AnthropicBackend
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        creds = {"claudeAiOauth": {
            "accessToken": "tok",
            "refreshToken": "ref",
            "expiresAt": int(time.time() * 1000) + 3_600_000,  # 1h from now
        }}
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps(creds))
        b = AnthropicBackend(credentials_path=str(creds_file))
        assert b.is_available() is True

    def test_unavailable_when_credentials_expired_and_refresh_fails(self, tmp_path, monkeypatch):
        import json, time
        import unittest.mock as mock
        from bot.llm import AnthropicBackend
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        creds = {"claudeAiOauth": {
            "accessToken": "tok",
            "refreshToken": "ref",
            "expiresAt": int(time.time() * 1000) - 1000,  # expired
        }}
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps(creds))
        # Mock refresh to fail so get_valid_token returns None
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.ok = False
            mock_post.return_value.status_code = 401
            mock_post.return_value.text = "Unauthorized"
            b = AnthropicBackend(credentials_path=str(creds_file))
            assert b.is_available() is False


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
