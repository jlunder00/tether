"""Tests for bot/conversation.py — SDK conversation loop."""
import asyncio
import pytest
import unittest.mock as mock
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_llm_response(content="ok", tool_calls=None, stop_reason="end_turn",
                      input_tokens=10, output_tokens=5):
    from bot.llm import LLMResponse, ToolCall
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def make_tool_call(name="get_plan", input=None, id="call_1"):
    from bot.llm import ToolCall
    return ToolCall(id=id, name=name, input=input or {})


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_returns_non_empty_string(self):
        from bot.conversation import build_system_prompt
        result = build_system_prompt(
            anchor_name="Morning",
            anchor_time="07:00",
            plan_summary="[ ] Task one",
            context_subjects=["Work/Project"],
            session_notes=None,
        )
        assert isinstance(result, str)
        assert len(result) > 50

    def test_includes_anchor_name(self):
        from bot.conversation import build_system_prompt
        result = build_system_prompt(
            anchor_name="Deep Work",
            anchor_time="09:00",
            plan_summary="[ ] Task one",
            context_subjects=[],
            session_notes=None,
        )
        assert "Deep Work" in result

    def test_includes_context_subjects(self):
        from bot.conversation import build_system_prompt
        result = build_system_prompt(
            anchor_name="Morning",
            anchor_time="07:00",
            plan_summary="",
            context_subjects=["Work/Alpha", "Health"],
            session_notes=None,
        )
        assert "Work/Alpha" in result
        assert "Health" in result

    def test_injects_session_notes_when_provided(self):
        from bot.conversation import build_system_prompt
        result = build_system_prompt(
            anchor_name="Morning",
            anchor_time="07:00",
            plan_summary="",
            context_subjects=[],
            session_notes="## Session Notes\nWorking on feature X.",
        )
        assert "Working on feature X" in result

    def test_session_notes_absent_when_none(self):
        from bot.conversation import build_system_prompt
        result = build_system_prompt(
            anchor_name="Morning",
            anchor_time="07:00",
            plan_summary="",
            context_subjects=[],
            session_notes=None,
        )
        assert "Session Notes" not in result


# ---------------------------------------------------------------------------
# conversation_loop
# ---------------------------------------------------------------------------

def _make_mock_router_for_loop(response_content="Done!", tool_calls=None, stop_reason="end_turn"):
    """Build a mock LLMRouter for conversation_loop tests."""
    from bot.llm import LLMResponse
    resp = LLMResponse(
        content=response_content,
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,
        input_tokens=10,
        output_tokens=5,
    )
    router = mock.MagicMock()
    router.complete = mock.AsyncMock(return_value=resp)
    return router


class TestConversationLoop:
    def test_returns_content_on_end_turn(self):
        from bot.conversation import conversation_loop
        router = _make_mock_router_for_loop("Done!")
        result = asyncio.run(conversation_loop(
            router=router,
            role="main_agent",
            messages=[{"role": "user", "content": "hello"}],
            system="sys",
            tools=[],
            tool_executor=None,
        ))
        assert result.content == "Done!"
        router.complete.assert_called_once()

    def test_loop_calls_router_complete_with_role(self):
        """conversation_loop must call router.complete(role=...) not backend.complete(model=...)."""
        from bot.conversation import conversation_loop
        router = _make_mock_router_for_loop("ok")
        asyncio.run(conversation_loop(
            router=router,
            role="subagent",
            messages=[{"role": "user", "content": "hi"}],
            system="sys",
            tools=[],
            tool_executor=None,
        ))
        call_kwargs = router.complete.call_args[1]
        assert call_kwargs.get("role") == "subagent"
        assert "model" not in call_kwargs  # model resolved inside router

    def test_executes_tool_and_continues(self):
        from bot.conversation import conversation_loop
        from bot.llm import LLMResponse

        call_sequence = [
            make_llm_response(content="", tool_calls=[make_tool_call("get_plan", {})],
                              stop_reason="tool_use"),
            make_llm_response(content="Plan fetched!", stop_reason="end_turn"),
        ]
        responses = iter(call_sequence)

        router = mock.MagicMock()
        router.complete = mock.AsyncMock(side_effect=lambda **kw: responses.__next__())

        async def fake_executor(tool_call):
            return {"ok": True, "content": "[ ] task one"}

        result = asyncio.run(conversation_loop(
            router=router,
            role="main_agent",
            messages=[{"role": "user", "content": "what's my plan?"}],
            system="sys",
            tools=[{"name": "get_plan", "description": "get plan", "input_schema": {}}],
            tool_executor=fake_executor,
        ))
        assert result.content == "Plan fetched!"

    def test_tool_result_appended_to_messages(self):
        from bot.conversation import conversation_loop
        captured_messages = []
        call_sequence = [
            make_llm_response(content="", tool_calls=[make_tool_call("get_plan", {}, id="c1")],
                              stop_reason="tool_use"),
            make_llm_response(content="done", stop_reason="end_turn"),
        ]
        responses = iter(call_sequence)

        async def capture_and_return(**kwargs):
            captured_messages.append(kwargs["messages"])
            return next(responses)

        router = mock.MagicMock()
        router.complete = mock.AsyncMock(side_effect=capture_and_return)

        asyncio.run(conversation_loop(
            router=router,
            role="main_agent",
            messages=[{"role": "user", "content": "hi"}],
            system="sys",
            tools=[],
            tool_executor=lambda tc: asyncio.coroutine(lambda: {"ok": True, "content": "plan data"})(),
        ))
        second_call_msgs = captured_messages[1]
        roles = [m["role"] for m in second_call_msgs]
        assert "tool" in roles or "user" in roles

    def test_stops_at_max_rounds(self):
        from bot.conversation import conversation_loop
        router = mock.MagicMock()
        router.complete = mock.AsyncMock(return_value=make_llm_response(
            content="", tool_calls=[make_tool_call("get_plan", {})], stop_reason="tool_use"))

        result = asyncio.run(conversation_loop(
            router=router,
            role="main_agent",
            messages=[{"role": "user", "content": "hi"}],
            system="sys",
            tools=[],
            tool_executor=lambda tc: asyncio.coroutine(lambda: {"ok": True, "content": "data"})(),
            max_rounds=3,
        ))
        assert isinstance(result.content, str)

    def test_handles_failed_tool_gracefully(self):
        from bot.conversation import conversation_loop
        call_sequence = [
            make_llm_response(content="", tool_calls=[make_tool_call("bad_tool", {})],
                              stop_reason="tool_use"),
            make_llm_response(content="recovered", stop_reason="end_turn"),
        ]
        responses = iter(call_sequence)
        router = mock.MagicMock()
        router.complete = mock.AsyncMock(side_effect=lambda **kw: responses.__next__())

        async def failing_executor(tc):
            raise RuntimeError("tool exploded")

        result = asyncio.run(conversation_loop(
            router=router,
            role="main_agent",
            messages=[{"role": "user", "content": "hi"}],
            system="sys",
            tools=[],
            tool_executor=failing_executor,
        ))
        assert isinstance(result.content, str)


# ---------------------------------------------------------------------------
# format_tool_result_message
# ---------------------------------------------------------------------------

class TestFormatToolResultMessage:
    def test_success_result_has_correct_shape(self):
        from bot.conversation import format_tool_result_message
        from bot.llm import ToolCall
        tc = ToolCall(id="c1", name="get_plan", input={})
        msg = format_tool_result_message(tc, {"ok": True, "content": "data"})
        assert msg["role"] in ("tool", "user")
        # Content must reference the tool call id
        assert "c1" in str(msg)

    def test_error_result_is_marked_as_error(self):
        from bot.conversation import format_tool_result_message
        from bot.llm import ToolCall
        tc = ToolCall(id="c2", name="bad_tool", input={})
        msg = format_tool_result_message(tc, {"ok": False, "content": "boom"}, is_error=True)
        assert "c2" in str(msg)
        assert "boom" in str(msg)


# ---------------------------------------------------------------------------
# handle_message — top-level entry point
# ---------------------------------------------------------------------------

class TestHandleMessage:
    def _make_mock_router(self, response_content="I updated your tasks."):
        """Returns a mock LLMRouter whose backends return a fixed response."""
        from bot.llm import LLMResponse
        fake_resp = LLMResponse(
            content=response_content,
            tool_calls=[],
            stop_reason="end_turn",
            input_tokens=10,
            output_tokens=5,
        )
        router = mock.MagicMock()
        router.complete = mock.AsyncMock(return_value=fake_resp)
        router.complete_fast = mock.AsyncMock(return_value=fake_resp)
        router.active_backend = mock.MagicMock()
        router.active_backend.complete = mock.AsyncMock(return_value=fake_resp)
        router.fast_backend = mock.MagicMock()
        router.fast_backend.complete = mock.AsyncMock(return_value=fake_resp)
        return router

    def test_returns_string_response(self, tmp_path):
        from bot.conversation import handle_message
        router = self._make_mock_router("All done!")
        result = asyncio.run(handle_message(
            user_text="What's on my plan?",
            router=router,
            db_path=str(tmp_path / "test.db"),
        ))
        assert isinstance(result, str)
        assert len(result) > 0

    def test_uses_quick_path_with_classifier_role(self, tmp_path):
        """Quick path calls router.complete(role='classifier')."""
        from bot.conversation import handle_message
        router = self._make_mock_router("Hi there!")

        result = asyncio.run(handle_message(
            user_text="hi",
            router=router,
            db_path=str(tmp_path / "test.db"),
            force_quick=True,
        ))
        assert isinstance(result, str)
        call_kwargs = router.complete.call_args[1]
        assert call_kwargs.get("role") == "classifier"
        router.active_backend.complete.assert_not_called()

    def test_full_path_uses_main_agent_role(self, tmp_path):
        """Full path calls router.complete(role='main_agent') via conversation_loop."""
        from bot.conversation import handle_message
        router = self._make_mock_router("Processed.")
        result = asyncio.run(handle_message(
            user_text="Update task 3 to done",
            router=router,
            db_path=str(tmp_path / "test.db"),
            force_full=True,
        ))
        assert isinstance(result, str)
        call_kwargs = router.complete.call_args[1]
        assert call_kwargs.get("role") == "main_agent"

    def test_custom_roles_forwarded(self, tmp_path):
        """role_quick and role_full are forwarded to router.complete()."""
        from bot.conversation import handle_message
        router = self._make_mock_router("ok")
        asyncio.run(handle_message(
            user_text="hi",
            router=router,
            db_path=str(tmp_path / "test.db"),
            force_full=True,
            role_full="subagent",
        ))
        call_kwargs = router.complete.call_args[1]
        assert call_kwargs.get("role") == "subagent"
