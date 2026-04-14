"""Tests for modular prompt sections."""
import pytest
from bot.prompt_sections import (
    build_prompt, resolve_sections, MODES,
    IDENTITY, PERSONALITY, SEPARATION_OF_DUTIES,
    _STATIC_SECTIONS, _DYNAMIC_SECTIONS,
)


@pytest.fixture
def ctx():
    return {
        "today": "2026-04-06",
        "anchor_name": "Deep Work",
        "anchor_time": "10:30",
        "plan_summary": "deep_work: [p] GPU pipeline deploy",
        "context_subjects": ["Intellipat", "Tether", "Thesis"],
        "session_notes": "Morning: reviewed GPU test results.",
    }


class TestResolve:
    def test_default_mode_is_scheduler(self):
        sections = resolve_sections()
        assert "IDENTITY" in sections
        assert "SEPARATION_OF_DUTIES" in sections
        assert "SCHEDULING_FOCUS" in sections

    def test_all_modes_exist(self):
        for mode in ["scheduler", "coach", "planner", "quick", "followup"]:
            sections = resolve_sections(mode)
            assert "IDENTITY" in sections

    def test_include_adds_section(self):
        sections = resolve_sections("quick", include=["TOOL_GUIDANCE"])
        assert "TOOL_GUIDANCE" in sections

    def test_exclude_removes_section(self):
        sections = resolve_sections("scheduler", exclude=["RESOURCE_CONSTRAINTS"])
        assert "RESOURCE_CONSTRAINTS" not in sections
        assert "IDENTITY" in sections  # others untouched

    def test_unknown_mode_falls_back_to_scheduler(self):
        sections = resolve_sections("nonexistent_mode")
        assert sections == resolve_sections("scheduler")


class TestBuildPrompt:
    def test_scheduler_contains_identity_and_duties(self, ctx):
        prompt = build_prompt("scheduler", ctx)
        assert "Tether" in prompt
        assert "ADHD accountability coach" in prompt
        assert "SCHEDULING and DAILY MANAGEMENT" in prompt

    def test_scheduler_contains_dynamic_state(self, ctx):
        prompt = build_prompt("scheduler", ctx)
        assert "2026-04-06" in prompt
        assert "Deep Work" in prompt
        assert "GPU pipeline deploy" in prompt
        assert "Intellipat" in prompt
        assert "Morning: reviewed" in prompt

    def test_coach_is_shorter_than_planner(self, ctx):
        coach = build_prompt("coach", ctx)
        planner = build_prompt("planner", ctx)
        assert len(coach) < len(planner)

    def test_quick_mode_minimal(self, ctx):
        prompt = build_prompt("quick", ctx)
        assert "TOOL_GUIDANCE" not in prompt
        assert "SESSION_AWARENESS" not in prompt
        assert "Tether" in prompt
        assert "Deep Work" in prompt

    def test_followup_mode_has_coaching(self, ctx):
        prompt = build_prompt("followup", ctx)
        assert "followup check-in" in prompt
        assert "gentle nudge" in prompt.lower() or "nudge" in prompt.lower()

    def test_planner_has_structured_guidance(self, ctx):
        prompt = build_prompt("planner", ctx)
        assert "thorough and structured" in prompt
        assert "bullet points" in prompt

    def test_missing_dynamic_ctx_omits_section(self):
        prompt = build_prompt("scheduler", ctx={"today": "2026-04-06",
                                                 "anchor_name": "General",
                                                 "anchor_time": "00:00"})
        assert "Available context entries" not in prompt
        assert "Session Notes" not in prompt
        assert "Today's plan" not in prompt

    def test_exclude_separation_of_duties(self, ctx):
        prompt = build_prompt("scheduler", ctx, exclude=["SEPARATION_OF_DUTIES"])
        assert "SCHEDULING and DAILY MANAGEMENT" not in prompt
        assert "Tether" in prompt  # identity still present

    def test_include_custom_section(self, ctx):
        prompt = build_prompt("quick", ctx, include=["SESSION_AWARENESS"])
        assert "multi-turn session" in prompt


class TestBuildSystemPromptIntegration:
    """Test that conversation.py's build_system_prompt delegates correctly."""

    def test_default_mode_is_scheduler(self):
        from bot.conversation import build_system_prompt
        prompt = build_system_prompt(
            anchor_name="The Grind",
            anchor_time="09:00",
            plan_summary="grind_am: [p] Leetcode",
            context_subjects=["Job Search"],
            session_notes=None,
        )
        assert "ADHD accountability coach" in prompt
        assert "SCHEDULING and DAILY MANAGEMENT" in prompt

    def test_quick_mode(self):
        from bot.conversation import build_system_prompt
        prompt = build_system_prompt(
            anchor_name="General",
            anchor_time="00:00",
            plan_summary="",
            context_subjects=[],
            session_notes=None,
            mode="quick",
        )
        assert "brief" in prompt.lower()
        assert "SESSION_AWARENESS" not in prompt

    def test_mode_passthrough(self):
        from bot.conversation import build_system_prompt
        prompt = build_system_prompt(
            anchor_name="General",
            anchor_time="00:00",
            plan_summary="",
            context_subjects=[],
            session_notes=None,
            mode="planner",
        )
        assert "thorough and structured" in prompt


class TestSectionRegistries:
    def test_all_static_keys_are_strings(self):
        for key, val in _STATIC_SECTIONS.items():
            assert isinstance(val, str), f"{key} is not a string"
            assert len(val) > 10, f"{key} is suspiciously short"

    def test_all_dynamic_keys_are_callable(self):
        for key, fn in _DYNAMIC_SECTIONS.items():
            assert callable(fn), f"{key} is not callable"

    def test_all_mode_keys_are_registered(self):
        for mode, keys in MODES.items():
            for key in keys:
                assert key in _STATIC_SECTIONS or key in _DYNAMIC_SECTIONS, \
                    f"Mode '{mode}' references unregistered section '{key}'"
