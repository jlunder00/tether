"""Tests for bot/state_monitor.py and bot/beacon.py — Beacon background agent."""
import asyncio
import time
import pytest
import unittest.mock as mock
from datetime import date, datetime, timedelta
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
    ])
    upsert_context_entry(db_path, "Work/Alpha", "Ongoing project.")
    return db_path


def make_router(triage_response="NO", action_response="Done."):
    """Router that returns triage_response for the first call, action_response for subsequent."""
    from bot.llm import LLMResponse
    call_count = 0

    async def fake_complete(**kwargs):
        nonlocal call_count
        call_count += 1
        content = triage_response if call_count == 1 else action_response
        return LLMResponse(content=content, tool_calls=[], stop_reason="end_turn",
                           input_tokens=10, output_tokens=5)

    router = mock.MagicMock()
    router.complete = mock.AsyncMock(side_effect=fake_complete)
    router.active_backend = mock.MagicMock()
    router.active_backend.complete = mock.AsyncMock(side_effect=fake_complete)
    return router


# ---------------------------------------------------------------------------
# State monitor — change recording
# ---------------------------------------------------------------------------

class TestRecordChange:
    def test_records_change_to_db(self, db_path):
        from bot.state_monitor import record_change, get_pending_score
        record_change(db_path, "task_done", "task-uuid-1")
        # debounce_minutes=0 to see just-inserted changes
        score = get_pending_score(db_path, debounce_minutes=0)
        assert score > 0

    def test_task_done_has_weight_2(self, db_path):
        from bot.state_monitor import record_change, get_pending_score, CHANGE_WEIGHTS
        record_change(db_path, "task_done", "t1")
        assert get_pending_score(db_path, debounce_minutes=0) == CHANGE_WEIGHTS["task_done"]

    def test_context_updated_has_weight_3(self, db_path):
        from bot.state_monitor import record_change, get_pending_score, CHANGE_WEIGHTS
        record_change(db_path, "context_updated", "Work/Alpha")
        assert get_pending_score(db_path, debounce_minutes=0) == CHANGE_WEIGHTS["context_updated"]

    def test_multiple_changes_accumulate(self, db_path):
        from bot.state_monitor import record_change, get_pending_score
        record_change(db_path, "task_done", "t1")
        record_change(db_path, "context_updated", "Work/Alpha")
        record_change(db_path, "task_created", "t2")
        score = get_pending_score(db_path, debounce_minutes=0)
        assert score >= 6  # 2 + 3 + 1

    def test_duplicate_entity_deduplicates(self, db_path):
        """3 updates to the same task count as 1 (max score)."""
        from bot.state_monitor import record_change, get_pending_score, CHANGE_WEIGHTS
        record_change(db_path, "task_done", "t1")
        record_change(db_path, "task_done", "t1")
        record_change(db_path, "task_done", "t1")
        score = get_pending_score(db_path, debounce_minutes=0)
        assert score == CHANGE_WEIGHTS["task_done"]  # deduped to 1

    def test_unknown_change_type_uses_default_weight(self, db_path):
        from bot.state_monitor import record_change, get_pending_score
        record_change(db_path, "unknown_type", "x")
        assert get_pending_score(db_path, debounce_minutes=0) >= 1


class TestConsumeChanges:
    def test_consume_resets_pending_score_to_zero(self, db_path):
        from bot.state_monitor import record_change, consume_changes, get_pending_score
        record_change(db_path, "task_done", "t1")
        record_change(db_path, "context_updated", "c1")
        summary = consume_changes(db_path)
        assert get_pending_score(db_path) == 0

    def test_consume_returns_summary_of_changes(self, db_path):
        from bot.state_monitor import record_change, consume_changes
        record_change(db_path, "task_done", "task-123")
        record_change(db_path, "context_updated", "Work/Alpha")
        summary = consume_changes(db_path)
        assert isinstance(summary, list)
        assert len(summary) == 2
        types = [c["change_type"] for c in summary]
        assert "task_done" in types
        assert "context_updated" in types

    def test_consume_only_returns_unconsumed(self, db_path):
        from bot.state_monitor import record_change, consume_changes, get_pending_score
        record_change(db_path, "task_done", "t1")
        consume_changes(db_path)                  # consume first batch
        record_change(db_path, "task_created", "t2")
        second = consume_changes(db_path)
        assert len(second) == 1
        assert second[0]["change_type"] == "task_created"


class TestDebounceWindow:
    def test_recent_changes_excluded_from_score(self, db_path):
        """Changes within debounce window should not be counted."""
        from bot.state_monitor import record_change, get_pending_score
        record_change(db_path, "task_done", "t1")
        # With default debounce, just-inserted changes aren't counted
        assert get_pending_score(db_path, debounce_minutes=10) == 0

    def test_old_changes_included_in_score(self, db_path):
        from bot.state_monitor import record_change, get_pending_score
        record_change(db_path, "task_done", "t1")
        _backdate_changes(db_path, minutes=15)
        assert get_pending_score(db_path, debounce_minutes=10) > 0

    def test_window_not_settled_when_recent_changes(self, db_path):
        from bot.state_monitor import record_change, is_window_settled
        record_change(db_path, "task_done", "t1")
        assert is_window_settled(db_path, debounce_minutes=10) is False

    def test_window_settled_when_all_changes_old(self, db_path):
        from bot.state_monitor import record_change, is_window_settled
        record_change(db_path, "task_done", "t1")
        _backdate_changes(db_path, minutes=15)
        assert is_window_settled(db_path, debounce_minutes=10) is True

    def test_window_not_settled_when_no_changes(self, db_path):
        from bot.state_monitor import is_window_settled
        assert is_window_settled(db_path) is False


class TestChangeWeights:
    def test_all_expected_types_defined(self):
        from bot.state_monitor import CHANGE_WEIGHTS
        expected = {"task_done", "task_blocked", "context_updated",
                    "plan_restructured", "acknowledgement", "task_created"}
        assert expected <= set(CHANGE_WEIGHTS.keys())

    def test_weights_are_positive_integers(self):
        from bot.state_monitor import CHANGE_WEIGHTS
        for k, v in CHANGE_WEIGHTS.items():
            assert isinstance(v, int) and v > 0


# ---------------------------------------------------------------------------
# should_trigger_beacon
# ---------------------------------------------------------------------------

def _backdate_changes(db_path, minutes=15):
    """Push all pending changes back in time so they're past the debounce window."""
    import sqlite3
    old_ts = (datetime.utcnow() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE state_monitor_log SET ts = ? WHERE consumed = 0", (old_ts,))
    conn.commit()
    conn.close()


class TestShouldTriggerBeacon:
    def test_false_when_score_below_threshold(self, db_path):
        from bot.state_monitor import record_change
        from bot.beacon import should_trigger_beacon
        record_change(db_path, "task_created", "t1")  # weight=1
        _backdate_changes(db_path)
        assert should_trigger_beacon(db_path, score_threshold=8, cooldown_minutes=0) is False

    def test_true_when_score_at_threshold_and_window_settled(self, db_path):
        from bot.state_monitor import record_change
        from bot.beacon import should_trigger_beacon
        # plan_restructured = 5, context_updated = 3 → total 8
        record_change(db_path, "plan_restructured", "today")
        record_change(db_path, "context_updated", "Work/Alpha")
        _backdate_changes(db_path)  # settle the window
        assert should_trigger_beacon(db_path, score_threshold=8, cooldown_minutes=0) is True

    def test_false_when_window_not_settled(self, db_path):
        """Recent changes still within debounce window — don't trigger."""
        from bot.state_monitor import record_change
        from bot.beacon import should_trigger_beacon
        record_change(db_path, "plan_restructured", "today")
        record_change(db_path, "context_updated", "Work/Alpha")
        # Don't backdate — changes are fresh
        assert should_trigger_beacon(db_path, score_threshold=8, cooldown_minutes=0) is False

    def test_anchor_transition_bypasses_score_threshold(self, db_path):
        """Anchor transition triggers Beacon even with low score."""
        from bot.state_monitor import record_change
        from bot.beacon import should_trigger_beacon
        record_change(db_path, "task_created", "t1")  # weight=1, below any threshold
        assert should_trigger_beacon(
            db_path, score_threshold=15, cooldown_minutes=0, is_anchor_transition=True
        ) is True

    def test_anchor_transition_respects_cooldown(self, db_path):
        from bot.state_monitor import record_change
        from bot.beacon import should_trigger_beacon, record_beacon_invocation
        record_change(db_path, "task_done", "t1")
        record_beacon_invocation(db_path)
        assert should_trigger_beacon(
            db_path, score_threshold=15, cooldown_minutes=30, is_anchor_transition=True
        ) is False

    def test_anchor_transition_false_when_no_pending_changes(self, db_path):
        from bot.beacon import should_trigger_beacon
        assert should_trigger_beacon(
            db_path, score_threshold=15, cooldown_minutes=0, is_anchor_transition=True
        ) is False

    def test_false_within_cooldown(self, db_path):
        from bot.state_monitor import record_change
        from bot.beacon import should_trigger_beacon, record_beacon_invocation
        record_change(db_path, "plan_restructured", "today")
        record_change(db_path, "context_updated", "Work/Alpha")
        _backdate_changes(db_path)
        record_beacon_invocation(db_path)
        assert should_trigger_beacon(db_path, score_threshold=8, cooldown_minutes=30) is False

    def test_true_after_cooldown_expires(self, db_path):
        from bot.state_monitor import record_change
        from bot.beacon import should_trigger_beacon, record_beacon_invocation
        import sqlite3
        record_change(db_path, "plan_restructured", "today")
        record_change(db_path, "context_updated", "Work/Alpha")
        _backdate_changes(db_path)
        # Record a beacon invocation 31 minutes ago
        old_ts = (datetime.utcnow() - timedelta(minutes=31)).isoformat()
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE beacon_state SET last_invoked_at = ? WHERE id = 1", (old_ts,))
        conn.commit()
        conn.close()
        assert should_trigger_beacon(db_path, score_threshold=8, cooldown_minutes=30) is True


# ---------------------------------------------------------------------------
# run_beacon — two-phase agent
# ---------------------------------------------------------------------------

class TestRunBeacon:
    def test_does_not_invoke_action_when_triage_says_no(self, seeded_db):
        from bot.beacon import run_beacon
        router = make_router(triage_response="NO nothing to do")

        changes = [
            {"change_type": "task_done", "entity_id": "t1", "score": 2},
        ]
        asyncio.run(run_beacon(
            router=router,
            db_path=seeded_db,
            changes=changes,
            model="claude-haiku-4-5-20251001",
        ))
        # Only one LLM call (triage), no action phase
        assert router.complete.call_count == 1

    def test_invokes_action_when_triage_says_yes(self, seeded_db):
        from bot.beacon import run_beacon
        router = make_router(triage_response="YES needs attention")

        changes = [
            {"change_type": "context_updated", "entity_id": "Work/Alpha", "score": 3},
            {"change_type": "plan_restructured", "entity_id": "today", "score": 5},
        ]
        asyncio.run(run_beacon(
            router=router,
            db_path=seeded_db,
            changes=changes,
            model="claude-haiku-4-5-20251001",
        ))
        # Two calls: triage + action
        assert router.complete.call_count >= 2

    def test_returns_result_dict(self, seeded_db):
        from bot.beacon import run_beacon
        router = make_router(triage_response="NO")

        result = asyncio.run(run_beacon(
            router=router,
            db_path=seeded_db,
            changes=[{"change_type": "task_done", "entity_id": "t1", "score": 2}],
            model="claude-haiku-4-5-20251001",
        ))
        assert isinstance(result, dict)
        assert "triggered" in result
        assert "message" in result

    def test_does_not_raise_on_llm_failure(self, seeded_db):
        from bot.beacon import run_beacon
        router = mock.MagicMock()
        router.complete = mock.AsyncMock(side_effect=RuntimeError("LLM down"))

        result = asyncio.run(run_beacon(
            router=router,
            db_path=seeded_db,
            changes=[{"change_type": "task_done", "entity_id": "t1", "score": 2}],
            model="claude-haiku-4-5-20251001",
        ))
        assert isinstance(result, dict)
        assert result.get("triggered") is False

    def test_triage_checks_for_yes_case_insensitively(self, seeded_db):
        from bot.beacon import run_beacon
        router = make_router(triage_response="yes, this needs review")
        changes = [{"change_type": "context_updated", "entity_id": "x", "score": 3}]
        asyncio.run(run_beacon(
            router=router,
            db_path=seeded_db,
            changes=changes,
            model="claude-haiku-4-5-20251001",
        ))
        assert router.complete.call_count >= 2
