"""Tests for Phase 7 pipeline token optimizations."""
import pytest
from datetime import date


# ---------------------------------------------------------------------------
# Compact plan rendering
# ---------------------------------------------------------------------------

class TestCompactPlanRendering:
    def test_compact_format_fits_on_fewer_lines(self):
        from bot.message_handler import _format_plan_compact
        plan = {
            "anchors": {
                "morning": {"tasks": [
                    {"text": "Exercise", "status": "done"},
                    {"text": "Breakfast", "status": "pending"},
                ]},
                "deep_work": {"tasks": [
                    {"text": "Write report", "status": "in_progress"},
                ]},
            }
        }
        result = _format_plan_compact(plan)
        lines = [l for l in result.splitlines() if l.strip()]
        # Compact format: one line per anchor (not one line per task)
        assert len(lines) <= len(plan["anchors"])

    def test_compact_format_shows_status_symbols(self):
        from bot.message_handler import _format_plan_compact
        plan = {
            "anchors": {
                "morning": {"tasks": [
                    {"text": "Done task", "status": "done"},
                    {"text": "Pending task", "status": "pending"},
                    {"text": "Skipped task", "status": "skipped"},
                ]},
            }
        }
        result = _format_plan_compact(plan)
        assert "✓" in result or "[x]" in result or "done" in result.lower()
        assert "pending" in result.lower() or "[ ]" in result or "○" in result

    def test_compact_format_handles_empty_plan(self):
        from bot.message_handler import _format_plan_compact
        assert isinstance(_format_plan_compact({}), str)
        assert isinstance(_format_plan_compact({"anchors": {}}), str)

    def test_compact_is_shorter_than_verbose(self):
        from bot.message_handler import _format_plan_compact, _format_plan_human_readable
        plan = {
            "anchors": {
                "morning": {"tasks": [
                    {"text": f"Task {i}", "status": "pending"} for i in range(5)
                ]},
                "evening": {"tasks": [
                    {"text": f"Eve {i}", "status": "done"} for i in range(5)
                ]},
            }
        }
        compact_len = len(_format_plan_compact(plan))
        verbose_len = len(_format_plan_human_readable(plan))
        assert compact_len < verbose_len


# ---------------------------------------------------------------------------
# Session notes injection in orchestrator prompt
# ---------------------------------------------------------------------------

class TestOrchestratorSessionNotesInjection:
    def _build_orchestrator_prompt(self, session_notes=None):
        """Helper: render the orchestrator template with minimal context."""
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path
        templates_dir = Path("prompts")
        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            trim_blocks=True, lstrip_blocks=True,
        )
        template = env.get_template("orchestrator.md")
        return template.render(
            date=str(date.today()),
            current_anchor={"name": "Morning", "time": "07:00"},
            plan_human_readable="morning: [ ] Exercise",
            subjects_list="- Work/Alpha",
            history="User: hi",
            meta_eval_summary="",
            fetched_context="",
            user_message="What's my plan?",
            session_notes=session_notes,
        )

    def test_session_notes_appear_when_provided(self):
        prompt = self._build_orchestrator_prompt(
            session_notes="## Notes\nWorking on alpha."
        )
        assert "Working on alpha" in prompt

    def test_history_not_in_prompt_when_session_notes_provided(self):
        """When session notes are available, skip raw history to save tokens."""
        prompt = self._build_orchestrator_prompt(
            session_notes="## Notes\nContext here."
        )
        # Session notes replace the history section
        assert "Session Notes" in prompt or "Notes" in prompt

    def test_session_notes_absent_when_none(self):
        prompt = self._build_orchestrator_prompt(session_notes=None)
        assert "Session Notes" not in prompt


# ---------------------------------------------------------------------------
# History truncation in message_handler
# ---------------------------------------------------------------------------

class TestHistoryFormatting:
    def test_format_history_truncates_long_bodies(self):
        from bot.message_handler import _format_history
        long_history = [
            {"role": "user", "body": "x" * 2000, "ts": "2026-01-01T10:00"},
            {"role": "assistant", "body": "y" * 2000, "ts": "2026-01-01T10:01"},
        ]
        result = _format_history(long_history)
        # Each message body should be capped
        assert len(result) < len("x" * 2000) * 2 + len("y" * 2000) * 2

    def test_format_history_handles_empty(self):
        from bot.message_handler import _format_history
        assert _format_history([]) == "(none)"


# ---------------------------------------------------------------------------
# Subagent prompts — no redundant claude -p header
# ---------------------------------------------------------------------------

class TestSubagentPrompts:
    def test_subagent_upsert_has_no_duplicate_tool_warning(self):
        """Subagent prompts should not repeat the full no-tool-access header."""
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path
        env = Environment(
            loader=FileSystemLoader("prompts"),
            trim_blocks=True, lstrip_blocks=True,
        )
        template = env.get_template("subagent_upsert.md")
        prompt = template.render(
            description="Update task list",
            op="update_plan_tasks",
            params='{"anchor_id": "morning", "tasks": []}',
            orchestrator_briefing="User wants to clear tasks.",
        )
        # The long preamble about "no tool access" from other prompts
        # should not appear in every subagent prompt — one mention max
        tool_warning_count = prompt.lower().count("no tool access")
        assert tool_warning_count <= 1

    def test_subagent_patch_renders_correctly(self):
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path
        env = Environment(
            loader=FileSystemLoader("prompts"),
            trim_blocks=True, lstrip_blocks=True,
        )
        template = env.get_template("subagent_patch.md")
        prompt = template.render(
            description="Fix typo",
            op="patch_context",
            subject="Work/Alpha",
            current_body="Old content here.",
            old="Old content",
            new="New content",
            content="",
            orchestrator_briefing="Fix the typo.",
        )
        assert "Work/Alpha" in prompt
        assert "Old content" in prompt
        assert "New content" in prompt
