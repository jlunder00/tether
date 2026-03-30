import json
import pytest
import subprocess
from datetime import date
from unittest.mock import patch, call as mock_call
from db.schema import init_db
from db.queries import get_anchors, upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry, get_context_entries

TODAY = str(date.today())

ANCHOR = {"id": "grind_am", "name": "The Grind", "time": "08:00",
          "duration_minutes": 120, "flexibility": "locked",
          "strictness": 4, "color": "#e05c5c", "position": 0}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_anchor(path, ANCHOR)
    upsert_plan(path, TODAY)
    upsert_tasks(path, TODAY, "grind_am", tasks=["Apply to 3 jobs"], notes="ML roles")
    upsert_context_entry(path, "Job Applications", "Priority 1.")
    return path


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
# call_claude timeout
# ---------------------------------------------------------------------------

def test_call_claude_raises_on_timeout():
    from bot.message_handler import call_claude
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 180)):
        with pytest.raises(RuntimeError, match="timed out"):
            call_claude("some prompt")


def test_call_claude_no_model_role_omits_model_flag():
    from bot.message_handler import call_claude
    mock_result = type("R", (), {"stdout": "hi", "returncode": 0})()
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        call_claude("test prompt")
    cmd = mock_run.call_args[0][0]
    assert "--model" not in cmd
    assert cmd == ["claude", "-p", "test prompt"]


def test_call_claude_with_model_role_injects_model_flag():
    from bot.message_handler import call_claude, _MODEL_DEFAULTS
    mock_result = type("R", (), {"stdout": "hi", "returncode": 0})()
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        with patch("bot.message_handler.load_config", side_effect=FileNotFoundError):
            call_claude("test prompt", model_role="orchestrator")
    cmd = mock_run.call_args[0][0]
    assert "--model" in cmd
    assert _MODEL_DEFAULTS["orchestrator"] in cmd


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
# apply_mutations — patch/append ops
# ---------------------------------------------------------------------------

def test_apply_mutations_append_context(db_path):
    from bot.message_handler import apply_mutations
    apply_mutations([{"op": "append_context", "subject": "Job Applications", "content": "New line."}], db_path, TODAY)
    entries = get_context_entries(db_path)
    body = next(e["body"] for e in entries if e["subject"] == "Job Applications")
    assert "Priority 1." in body
    assert "New line." in body


def test_apply_mutations_patch_context(db_path):
    from bot.message_handler import apply_mutations
    apply_mutations([{"op": "patch_context", "subject": "Job Applications",
                      "old": "Priority 1.", "new": "Priority updated."}], db_path, TODAY)
    entries = get_context_entries(db_path)
    body = next(e["body"] for e in entries if e["subject"] == "Job Applications")
    assert "Priority updated." in body
    assert "Priority 1." not in body


def test_apply_mutations_patch_context_remove(db_path):
    from bot.message_handler import apply_mutations
    apply_mutations([{"op": "patch_context", "subject": "Job Applications",
                      "old": "Priority 1.", "new": ""}], db_path, TODAY)
    entries = get_context_entries(db_path)
    body = next(e["body"] for e in entries if e["subject"] == "Job Applications")
    assert "Priority 1." not in body


def test_apply_mutations_patch_context_missing_subject(db_path, caplog):
    from bot.message_handler import apply_mutations
    apply_mutations([{"op": "patch_context", "subject": "Nonexistent",
                      "old": "x", "new": "y"}], db_path, TODAY)
    # Should warn but not raise


# ---------------------------------------------------------------------------
# handle_message: slash commands
# ---------------------------------------------------------------------------

def test_handle_check_in_inserts_db_row(db_path):
    from bot.message_handler import handle_message
    from db.queries import get_plan
    with patch("bot.message_handler.call_claude", return_value="Great progress!"):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("/check-in applied to 2 jobs :: about to start third", [].append)
    plan = get_plan(db_path, TODAY)
    assert len(plan["check_in_log"]) == 1
    assert plan["check_in_log"][0]["accomplished"] == "applied to 2 jobs"


def test_handle_update_context_saves_to_db(db_path):
    from bot.message_handler import handle_message
    with patch("bot.message_handler.call_claude", return_value="Got it."):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("/tether-update-context Thesis :: Working on chapter 3", [].append)
    entries = get_context_entries(db_path)
    assert any(e["subject"] == "Thesis" for e in entries)


def test_handle_update_plan_saves_tasks(db_path):
    from bot.message_handler import handle_message
    from db.queries import get_plan
    with patch("bot.message_handler.call_claude", return_value="Updated!"):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("/update-plan grind_am :: New task 1; New task 2", [].append)
    plan = get_plan(db_path, TODAY)
    assert plan["anchors"]["grind_am"]["tasks"] == ["New task 1", "New task 2"]


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


# ---------------------------------------------------------------------------
# handle_message — persists conversation turn
# ---------------------------------------------------------------------------

def test_handle_message_persists_conversation_turn(db_path):
    from bot.message_handler import handle_message
    from db.queries import get_recent_history
    orch_conv = [{"role": "orchestrator", "body": "User wants a status check.", "round": 0}]
    with patch("bot.message_handler._run_v2_planning_loop",
               return_value=([], [], [], orch_conv)), \
         patch("bot.message_handler.call_satisfaction_eval",
               return_value={"satisfied": True, "issues": [], "replan_needed": False}), \
         patch("bot.message_handler.call_response_builder", return_value="All good!"):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("How am I doing?", [].append)
    history = get_recent_history(db_path)
    assert any(r["role"] == "user" and r["body"] == "How am I doing?" for r in history)
    assert any(r["role"] == "assistant" and r["body"] == "All good!" for r in history)


# ---------------------------------------------------------------------------
# _fetch_requested_context
# ---------------------------------------------------------------------------

def test_fetch_context_entry(db_path):
    upsert_context_entry(db_path, "Intellipat", "Main entry.")
    upsert_context_entry(db_path, "Intellipat/Backend", "Backend details.")
    from bot.message_handler import _fetch_requested_context
    result = _fetch_requested_context(
        [{"kind": "context_entry", "subject": "Intellipat"}], db_path, round_num=1
    )
    assert "Main entry." in result
    assert "Backend details." in result
    assert "Fetched context (round 1)" in result


def test_fetch_context_entry_not_found(db_path):
    from bot.message_handler import _fetch_requested_context
    result = _fetch_requested_context(
        [{"kind": "context_entry", "subject": "Nonexistent"}], db_path, round_num=1
    )
    assert "not found" in result


def test_fetch_plan(db_path):
    from bot.message_handler import _fetch_requested_context
    from db.queries import upsert_plan, upsert_tasks
    upsert_plan(db_path, "2026-03-30")
    upsert_tasks(db_path, "2026-03-30", "grind_am", ["Apply to jobs"], notes="")
    result = _fetch_requested_context(
        [{"kind": "plan", "date": "2026-03-30"}], db_path, round_num=1
    )
    assert "Apply to jobs" in result
    assert "2026-03-30" in result


def test_fetch_anchor_detail(db_path):
    from bot.message_handler import _fetch_requested_context
    result = _fetch_requested_context(
        [{"kind": "anchor_detail", "anchor_id": "grind_am"}], db_path, round_num=1
    )
    assert "grind_am" in result
    assert "The Grind" in result


def test_fetch_check_in_log(db_path):
    from bot.message_handler import _fetch_requested_context
    from db.queries import insert_check_in
    insert_check_in(db_path, TODAY, "grind_am", "Applied to 2 jobs", "on track")
    result = _fetch_requested_context(
        [{"kind": "check_in_log", "date": TODAY}], db_path, round_num=1
    )
    assert "Applied to 2 jobs" in result


def test_fetch_multiple_kinds(db_path):
    from bot.message_handler import _fetch_requested_context
    upsert_context_entry(db_path, "General", "General notes.")
    result = _fetch_requested_context([
        {"kind": "context_entry", "subject": "General"},
        {"kind": "anchor_detail", "anchor_id": "grind_am"},
    ], db_path, round_num=2)
    assert "General notes." in result
    assert "The Grind" in result


# ---------------------------------------------------------------------------
# handle_message — v2 planning loop
# ---------------------------------------------------------------------------

def test_handle_message_loops_on_request_context(db_path):
    """Planning loop makes one context fetch then commits."""
    from bot.message_handler import _run_v2_planning_loop, MAX_PLANNING_ROUNDS
    upsert_context_entry(db_path, "Job Applications", "Priority 1.")

    # Round 0: orchestrator reasons; meta_eval fetches context, not done
    # Round 1: orchestrator reasons; meta_eval stages chat mutation, done
    meta_round0 = json.dumps({
        "summary": "Fetching Job Applications context first.",
        "context_to_fetch": [{"kind": "context_entry", "subject": "Job Applications"}],
        "mutation_plan": [],
        "orchestrator_done": False,
    })
    meta_round1 = json.dumps({
        "summary": "Have context. Answering question.",
        "context_to_fetch": [],
        "mutation_plan": [{"id": "c1", "type": "chat", "description": "Answer", "message": "Here you go."}],
        "orchestrator_done": True,
    })
    meta_calls = iter([meta_round0, meta_round1])
    anchors = get_anchors(db_path)
    today = str(date.today())

    with patch("bot.message_handler.call_orchestrator", return_value="Reasoning text."), \
         patch("bot.message_handler.call_claude", side_effect=lambda p, **kw: next(meta_calls)):
        mutation_plan, reports, chat_messages, orch_conv = _run_v2_planning_loop(
            "What's my job app status?", anchors, [], db_path, today
        )

    # Two orchestrator rounds happened (meta was called twice)
    assert len(orch_conv) == 2
    # chat mutation captured
    assert chat_messages == ["Here you go."]
    assert reports == []


def test_handle_message_force_dispatch_after_max_rounds(db_path):
    """Loop terminates after MAX_PLANNING_ROUNDS even if meta_eval never sets done."""
    from bot.message_handler import _run_v2_planning_loop, MAX_PLANNING_ROUNDS
    not_done = json.dumps({
        "summary": "Still thinking.",
        "context_to_fetch": [],
        "mutation_plan": [],
        "orchestrator_done": False,
    })
    anchors = get_anchors(db_path)
    today = str(date.today())

    call_count = {"n": 0}
    def count_calls(p, **kw):
        call_count["n"] += 1
        return not_done

    with patch("bot.message_handler.call_orchestrator", return_value="Reasoning."), \
         patch("bot.message_handler.call_claude", side_effect=count_calls), \
         patch("bot.message_handler.dispatch_typed_subagents", return_value=([], [])):
        _run_v2_planning_loop("Help.", anchors, [], db_path, today)

    # Should have called meta_eval exactly MAX_PLANNING_ROUNDS + 1 times (rounds 0..MAX)
    assert call_count["n"] == MAX_PLANNING_ROUNDS + 1
