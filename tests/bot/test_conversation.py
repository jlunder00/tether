"""Tests for bot/conversation.py — system prompt + tool result formatting."""
import pytest


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
# format_tool_result_message
# ---------------------------------------------------------------------------

class TestFormatToolResultMessage:
    def test_success_result_has_correct_shape(self):
        from bot.conversation import format_tool_result_message
        from bot.llm import ToolCall
        tc = ToolCall(id="c1", name="get_plan", input={})
        msg = format_tool_result_message(tc, {"ok": True, "content": "data"})
        assert msg["role"] in ("tool", "user")
        assert "c1" in str(msg)

    def test_error_result_is_marked_as_error(self):
        from bot.conversation import format_tool_result_message
        from bot.llm import ToolCall
        tc = ToolCall(id="c2", name="bad_tool", input={})
        msg = format_tool_result_message(tc, {"ok": False, "content": "boom"}, is_error=True)
        assert "c2" in str(msg)
        assert "boom" in str(msg)
