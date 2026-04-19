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
# call_claude — async, uses asyncio.create_subprocess_exec
# ---------------------------------------------------------------------------

def _make_proc(stdout: bytes = b"response", returncode: int = 0):
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.kill = AsyncMock()
    proc.wait = AsyncMock()
    proc.returncode = returncode
    return proc


@pytest.mark.asyncio
async def test_call_claude_returns_stdout():
    from bot.message_handler import call_claude
    proc = _make_proc(b"hello world")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await call_claude("test prompt")
    assert result == "hello world"


@pytest.mark.asyncio
async def test_call_claude_no_model_role_omits_model_flag():
    from bot.message_handler import call_claude
    proc = _make_proc(b"hi")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await call_claude("test prompt")
    cmd = mock_exec.call_args[0]
    assert "--model" not in cmd
    assert "claude" == cmd[0]
    assert "--strict-mcp-config" in cmd
    assert "test prompt" in cmd


@pytest.mark.asyncio
async def test_call_claude_with_model_role_injects_model_flag():
    from bot.message_handler import call_claude, _MODEL_DEFAULTS
    proc = _make_proc(b"hi")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec, \
         patch("bot.message_handler.load_config", side_effect=FileNotFoundError):
        await call_claude("test prompt", model_role="orchestrator")
    cmd = mock_exec.call_args[0]
    assert "--model" in cmd
    assert _MODEL_DEFAULTS["orchestrator"] in cmd


@pytest.mark.asyncio
async def test_call_claude_raises_on_timeout():
    from bot.message_handler import call_claude
    proc = AsyncMock()
    proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    proc.kill = AsyncMock()
    proc.wait = AsyncMock()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(RuntimeError, match="timed out"):
            await call_claude("some prompt", timeout=1)


@pytest.mark.asyncio
async def test_call_claude_includes_strict_mcp_config():
    from bot.message_handler import call_claude
    proc = _make_proc(b"hi")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
        await call_claude("test prompt", model_role="orchestrator")
    assert "--strict-mcp-config" in mock_exec.call_args[0]


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
