"""Tests for bot/llm.py — LLM abstraction layer."""
import pytest
from dataclasses import fields
from abc import ABC


# ---------------------------------------------------------------------------
# Dataclass structure
# ---------------------------------------------------------------------------

class TestLLMResponseDataclass:
    def test_has_required_fields(self):
        from bot.llm import LLMResponse
        field_names = {f.name for f in fields(LLMResponse)}
        assert field_names >= {"content", "tool_calls", "stop_reason",
                               "input_tokens", "output_tokens"}

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
    def test_has_required_fields(self):
        from bot.llm import ToolCall
        field_names = {f.name for f in fields(ToolCall)}
        assert field_names >= {"id", "name", "input"}

    def test_can_be_constructed(self):
        from bot.llm import ToolCall
        tc = ToolCall(id="call_1", name="get_plan", input={"date": "today"})
        assert tc.id == "call_1"
        assert tc.name == "get_plan"
        assert tc.input == {"date": "today"}


# ---------------------------------------------------------------------------
# LLMBackend ABC
# ---------------------------------------------------------------------------

class TestLLMBackendABC:
    def test_cannot_be_instantiated_directly(self):
        from bot.llm import LLMBackend
        with pytest.raises(TypeError):
            LLMBackend()

    def test_is_abstract_base_class(self):
        from bot.llm import LLMBackend
        assert issubclass(LLMBackend, ABC)

    def test_complete_is_abstract(self):
        from bot.llm import LLMBackend
        import inspect
        assert "complete" in LLMBackend.__abstractmethods__

    def test_is_available_is_abstract(self):
        from bot.llm import LLMBackend
        assert "is_available" in LLMBackend.__abstractmethods__

    def test_concrete_subclass_must_implement_both_methods(self):
        from bot.llm import LLMBackend
        class Incomplete(LLMBackend):
            pass
        with pytest.raises(TypeError):
            Incomplete()


# ---------------------------------------------------------------------------
# PipelineBackend
# ---------------------------------------------------------------------------

class TestPipelineBackend:
    def test_is_always_available(self):
        from bot.llm import PipelineBackend
        b = PipelineBackend()
        assert b.is_available() is True

    def test_complete_raises_on_missing_claude_cli(self, monkeypatch):
        """complete() should raise RuntimeError if claude binary not found."""
        from bot.llm import PipelineBackend
        import subprocess
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("claude not found")),
        )
        b = PipelineBackend()
        with pytest.raises((RuntimeError, FileNotFoundError)):
            import asyncio
            asyncio.run(b.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="you are helpful",
                model="claude-haiku-4-5-20251001",
            ))

    def test_complete_returns_llm_response(self, monkeypatch):
        from bot.llm import PipelineBackend, LLMResponse
        import subprocess

        fake_result = type("R", (), {"stdout": "hello from claude\n", "returncode": 0})()
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_result)

        b = PipelineBackend()
        import asyncio
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


# ---------------------------------------------------------------------------
# LLMRouter — backend selection
# ---------------------------------------------------------------------------

class TestLLMRouter:
    def test_falls_back_to_pipeline_when_nothing_else_available(self, monkeypatch, tmp_path):
        # boto3 is not installed in this env → AWSBedrockBackend.is_available() returns False
        # via its except Exception handler, so no mocking needed
        from bot.llm import LLMRouter, PipelineBackend
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        router = LLMRouter(credentials_path=str(tmp_path / "nope.json"))
        assert isinstance(router.active_backend, PipelineBackend)

    def test_prefers_anthropic_when_api_key_available(self, monkeypatch, tmp_path):
        from bot.llm import LLMRouter, AnthropicBackend
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        router = LLMRouter(credentials_path=str(tmp_path / "nope.json"))
        assert isinstance(router.active_backend, AnthropicBackend)

    def test_complete_delegates_to_active_backend(self, monkeypatch, tmp_path):
        from bot.llm import LLMRouter, LLMResponse
        import unittest.mock as mock
        import asyncio
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        router = LLMRouter(credentials_path=str(tmp_path / "nope.json"))
        fake_resp = LLMResponse("hi", [], "end_turn", 1, 1)
        async def fake_complete(**kwargs):
            return fake_resp
        with mock.patch.object(router.active_backend, "complete", side_effect=fake_complete):
            result = asyncio.run(router.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="sys",
                model="claude-haiku-4-5-20251001",
            ))
        assert result.content == "hi"


# ---------------------------------------------------------------------------
# Tool schema adapters
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
