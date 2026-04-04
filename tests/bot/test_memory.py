"""Tests for bot/memory.py — session notes, event-driven commits, compaction."""
import asyncio
import json
import pytest
import unittest.mock as mock
from pathlib import Path
from datetime import date
from db.schema import init_db


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    init_db(str(p))
    return str(p)


@pytest.fixture
def seeded_db(db_path):
    from db.queries import upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry
    today = date.today().isoformat()
    upsert_anchor(db_path, {
        "id": "morning", "name": "Morning", "time": "07:00",
        "duration_minutes": 60, "flexibility": "locked",
        "strictness": 3, "color": "#fff", "position": 0,
    })
    upsert_plan(db_path, today)
    upsert_tasks(db_path, today, "morning", [
        {"text": "Exercise", "status": "done", "position": 0},
        {"text": "Review notes", "status": "pending", "position": 1},
    ])
    upsert_context_entry(db_path, "Work/Alpha", "Ongoing project alpha.")
    return db_path


def make_router(response_text="Summary of what happened."):
    from bot.llm import LLMResponse
    router = mock.MagicMock()
    router.complete = mock.AsyncMock(return_value=LLMResponse(
        content=response_text,
        tool_calls=[],
        stop_reason="end_turn",
        input_tokens=20,
        output_tokens=10,
    ))
    return router


# ---------------------------------------------------------------------------
# Session notes — read/write
# ---------------------------------------------------------------------------

class TestReadSessionNotes:
    def test_returns_none_when_file_missing(self, tmp_path):
        from bot.memory import read_session_notes
        result = read_session_notes(str(tmp_path / "notes.md"))
        assert result is None

    def test_returns_content_when_file_exists(self, tmp_path):
        from bot.memory import read_session_notes
        f = tmp_path / "notes.md"
        f.write_text("# Session Notes\nWorking on alpha.")
        result = read_session_notes(str(f))
        assert result == "# Session Notes\nWorking on alpha."

    def test_returns_none_for_empty_file(self, tmp_path):
        from bot.memory import read_session_notes
        f = tmp_path / "notes.md"
        f.write_text("")
        result = read_session_notes(str(f))
        assert result is None


class TestWriteSessionNotes:
    def test_creates_file_with_content(self, tmp_path):
        from bot.memory import write_session_notes
        f = tmp_path / "notes.md"
        write_session_notes("# Notes\nContent here.", str(f))
        assert f.read_text() == "# Notes\nContent here."

    def test_overwrites_existing_content(self, tmp_path):
        from bot.memory import write_session_notes
        f = tmp_path / "notes.md"
        f.write_text("old content")
        write_session_notes("new content", str(f))
        assert f.read_text() == "new content"

    def test_creates_parent_directories(self, tmp_path):
        from bot.memory import write_session_notes
        f = tmp_path / "subdir" / "notes.md"
        write_session_notes("content", str(f))
        assert f.exists()


# ---------------------------------------------------------------------------
# Session notes update (LLM summarization, fire-and-forget)
# ---------------------------------------------------------------------------

class TestUpdateSessionNotes:
    def test_writes_llm_response_to_notes_file(self, tmp_path, seeded_db):
        from bot.memory import update_session_notes
        notes_path = str(tmp_path / "notes.md")
        router = make_router("## Updated session notes\nCompleted exercise.")

        asyncio.run(update_session_notes(
            router=router,
            db_path=seeded_db,
            notes_path=notes_path,
            role="summarizer",
        ))

        content = Path(notes_path).read_text()
        assert "Completed exercise" in content

    def test_calls_router_with_summary_prompt(self, tmp_path, seeded_db):
        from bot.memory import update_session_notes
        router = make_router("Notes updated.")

        asyncio.run(update_session_notes(
            router=router,
            db_path=seeded_db,
            notes_path=str(tmp_path / "notes.md"),
            role="summarizer",
        ))

        assert router.complete.called
        call_kwargs = router.complete.call_args[1]
        prompt = str(call_kwargs.get("messages", ""))
        # Should reference session notes structure
        assert len(prompt) > 0

    def test_does_not_raise_on_llm_failure(self, tmp_path, seeded_db):
        from bot.memory import update_session_notes
        router = mock.MagicMock()
        router.complete = mock.AsyncMock(side_effect=RuntimeError("LLM down"))

        # Should swallow the error — fire-and-forget
        asyncio.run(update_session_notes(
            router=router,
            db_path=seeded_db,
            notes_path=str(tmp_path / "notes.md"),
            role="summarizer",
        ))


# ---------------------------------------------------------------------------
# Anchor transition memory commit
# ---------------------------------------------------------------------------

class TestCommitAnchorTransition:
    def test_appends_summary_to_context_entry(self, tmp_path, seeded_db):
        from bot.memory import commit_anchor_transition
        from db.queries import get_context_entries
        router = make_router("Morning anchor complete. Exercise done.")

        asyncio.run(commit_anchor_transition(
            router=router,
            db_path=seeded_db,
            anchor_id="morning",
            notes_path=str(tmp_path / "notes.md"),
            role="summarizer",
        ))

        entries = {e["subject"]: e for e in get_context_entries(seeded_db)}
        # Should have created or updated an anchor log entry
        anchor_subjects = [s for s in entries if "morning" in s.lower() or "Morning" in s]
        assert len(anchor_subjects) > 0 or any("log" in s.lower() for s in entries)

    def test_resets_session_notes_after_transition(self, tmp_path, seeded_db):
        from bot.memory import commit_anchor_transition, read_session_notes
        notes_path = str(tmp_path / "notes.md")
        Path(notes_path).write_text("## Old session notes\nStale content.")

        router = make_router("Transition summary.")

        asyncio.run(commit_anchor_transition(
            router=router,
            db_path=seeded_db,
            anchor_id="morning",
            notes_path=notes_path,
            role="summarizer",
        ))

        # Notes should be reset/updated for the new anchor
        new_notes = read_session_notes(notes_path)
        assert new_notes is None or "Stale content" not in (new_notes or "")

    def test_does_not_raise_on_unknown_anchor(self, tmp_path, db_path):
        from bot.memory import commit_anchor_transition
        router = make_router("Summary.")
        # Should not crash — unknown anchor just means no tasks to summarize
        asyncio.run(commit_anchor_transition(
            router=router,
            db_path=db_path,
            anchor_id="nonexistent",
            notes_path=str(tmp_path / "notes.md"),
            role="summarizer",
        ))


# ---------------------------------------------------------------------------
# Significant mutation memory commit
# ---------------------------------------------------------------------------

class TestCommitSignificantMutations:
    def test_appends_summary_when_enough_mutations(self, tmp_path, seeded_db):
        from bot.memory import commit_significant_mutations
        from db.queries import get_context_entries
        router = make_router("Updated 3 tasks and one context entry.")

        changes = [
            {"type": "task_update", "description": "Exercise → done"},
            {"type": "task_update", "description": "Review → in_progress"},
            {"type": "context_update", "description": "Work/Alpha updated"},
        ]

        asyncio.run(commit_significant_mutations(
            router=router,
            db_path=seeded_db,
            changes=changes,
            notes_path=str(tmp_path / "notes.md"),
            role="summarizer",
        ))

        # LLM should have been called
        assert router.complete.called

    def test_skips_when_too_few_mutations(self, tmp_path, seeded_db):
        from bot.memory import commit_significant_mutations
        router = make_router("One change.")

        changes = [{"type": "task_update", "description": "One thing"}]

        asyncio.run(commit_significant_mutations(
            router=router,
            db_path=seeded_db,
            changes=changes,
            notes_path=str(tmp_path / "notes.md"),
            role="summarizer",
        ))

        # With only 1 change, should skip the LLM call
        assert not router.complete.called

    def test_threshold_is_configurable(self, tmp_path, seeded_db):
        from bot.memory import commit_significant_mutations
        router = make_router("Two changes summary.")

        changes = [
            {"type": "task_update", "description": "A"},
            {"type": "task_update", "description": "B"},
        ]

        asyncio.run(commit_significant_mutations(
            router=router,
            db_path=seeded_db,
            changes=changes,
            notes_path=str(tmp_path / "notes.md"),
            role="summarizer",
            threshold=2,
        ))

        assert router.complete.called


# ---------------------------------------------------------------------------
# Emergency compaction (90% context threshold)
# ---------------------------------------------------------------------------

class TestShouldCompact:
    def test_returns_false_for_short_conversation(self):
        from bot.memory import should_compact
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert should_compact(messages, context_limit=200_000) is False

    def test_returns_true_when_above_threshold(self):
        from bot.memory import should_compact
        # Each message ~100 chars, 1000 messages ~ 100K chars ~ 25K tokens
        messages = [
            {"role": "user", "content": "x" * 100}
            for _ in range(1000)
        ]
        # With a tiny limit it should trigger
        assert should_compact(messages, context_limit=1000) is True

    def test_threshold_is_90_percent(self):
        from bot.memory import should_compact
        # context_limit is in tokens; 4 chars = ~1 token
        # 356 chars / 4 = 89 tokens → 89/100 = 89% → no compact
        content = "x" * 356
        messages = [{"role": "user", "content": content}]
        assert should_compact(messages, context_limit=100) is False

        # 364 chars / 4 = 91 tokens → 91/100 = 91% → compact
        content = "x" * 364
        messages = [{"role": "user", "content": content}]
        assert should_compact(messages, context_limit=100) is True


class TestCompactConversation:
    def test_returns_shorter_message_list(self, tmp_path):
        from bot.memory import compact_conversation
        router = make_router("Summary of conversation: user asked about tasks.")

        messages = [
            {"role": "user", "content": f"message {i}"}
            for i in range(20)
        ]

        result = asyncio.run(compact_conversation(
            messages=messages,
            router=router,
            role="summarizer",
        ))

        assert len(result) < len(messages)
        assert isinstance(result, list)

    def test_preserved_summary_is_in_result(self, tmp_path):
        from bot.memory import compact_conversation
        router = make_router("Summary: worked on alpha project.")

        messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]

        result = asyncio.run(compact_conversation(
            messages=messages,
            router=router,
            role="summarizer",
        ))

        all_content = " ".join(
            str(m.get("content", "")) for m in result
        )
        assert "Summary" in all_content or "alpha" in all_content

    def test_returns_original_on_llm_failure(self):
        from bot.memory import compact_conversation
        router = mock.MagicMock()
        router.complete = mock.AsyncMock(side_effect=RuntimeError("LLM down"))

        messages = [{"role": "user", "content": f"msg {i}"} for i in range(5)]

        result = asyncio.run(compact_conversation(
            messages=messages,
            router=router,
            role="summarizer",
        ))

        # Fallback: return original messages unchanged
        assert result == messages
