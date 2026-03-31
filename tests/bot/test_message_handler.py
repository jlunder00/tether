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
    assert cmd == ["claude", "-p", "--strict-mcp-config", "test prompt"]


def test_call_claude_includes_strict_mcp_config():
    from bot.message_handler import call_claude
    mock_result = type("R", (), {"stdout": "hi", "returncode": 0})()
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        call_claude("test prompt", model_role="orchestrator")
    cmd = mock_run.call_args[0][0]
    assert "--strict-mcp-config" in cmd


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
    assert [t["text"] for t in plan["anchors"]["grind_am"]["tasks"]] == ["New task 1", "New task 2"]


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


# ---------------------------------------------------------------------------
# call_meta_eval — valid JSON, repair escalation, sentinel
# ---------------------------------------------------------------------------

def _meta_valid():
    return json.dumps({
        "summary": "Staging a plan update.",
        "context_to_fetch": [],
        "mutation_plan": [{"id": "m1", "type": "chat", "description": "Hi", "message": "Hello!"}],
        "orchestrator_done": True,
    })


def _meta_eval_kwargs(db_path):
    from db.queries import get_anchors
    return dict(
        orchestrator_conversation=[{"role": "orchestrator", "body": "Say hi", "round": 0}],
        current_mutation_plan=[],
        fetched_context_log=[],
        anchors=get_anchors(db_path),
        all_subjects=["Job Applications"],
        available_dates=[TODAY],
        today=TODAY,
        round_num=0,
        max_rounds=4,
        force_done=False,
    )


def test_call_meta_eval_valid_json(db_path):
    from bot.message_handler import call_meta_eval
    with patch("bot.message_handler.call_claude", return_value=_meta_valid()):
        result = call_meta_eval(**_meta_eval_kwargs(db_path))
    assert result["summary"] == "Staging a plan update."
    assert result["orchestrator_done"] is True
    assert result["mutation_plan"][0]["type"] == "chat"
    assert "_parse_error" not in result


def test_call_meta_eval_repair_escalation_haiku_x2_then_sonnet(db_path):
    """meta_eval bad → repair haiku x2 bad → repair sonnet succeeds."""
    from bot.message_handler import call_meta_eval
    # calls: meta_eval, repair-haiku-0, repair-haiku-1, repair-sonnet-2
    side_effects = ["not json", "not json", "not json", _meta_valid()]
    with patch("bot.message_handler.call_claude", side_effect=side_effects):
        result = call_meta_eval(**_meta_eval_kwargs(db_path))
    assert result["orchestrator_done"] is True
    assert "_parse_error" not in result


def test_call_meta_eval_all_repairs_fail_returns_sentinel(db_path):
    """All 4 calls return bad JSON → sentinel with _parse_error: True."""
    from bot.message_handler import call_meta_eval
    prior_plan = [{"id": "m0", "type": "chat", "description": "prev"}]
    kwargs = _meta_eval_kwargs(db_path)
    kwargs["current_mutation_plan"] = prior_plan
    with patch("bot.message_handler.call_claude", return_value="not json"):
        result = call_meta_eval(**kwargs)
    assert result["_parse_error"] is True
    assert result["orchestrator_done"] is False
    # preserves the prior mutation plan
    assert result["mutation_plan"] == prior_plan


# ---------------------------------------------------------------------------
# _run_v2_planning_loop — parse error counter aborts
# ---------------------------------------------------------------------------

def test_run_v2_planning_loop_aborts_on_repeated_parse_errors(db_path):
    """Three consecutive _parse_error responses should raise RuntimeError."""
    from bot.message_handler import _run_v2_planning_loop
    anchors = get_anchors(db_path)
    sentinel = {
        "summary": "error",
        "context_to_fetch": [],
        "mutation_plan": [],
        "orchestrator_done": False,
        "_parse_error": True,
    }
    with patch("bot.message_handler.call_orchestrator", return_value="thinking."), \
         patch("bot.message_handler.call_meta_eval", return_value=sentinel):
        with pytest.raises(RuntimeError, match="planning process"):
            _run_v2_planning_loop("help me", anchors, [], db_path, TODAY)


# ---------------------------------------------------------------------------
# dispatch_typed_subagents — routing
# ---------------------------------------------------------------------------

def test_dispatch_typed_subagents_routes_upsert_mutation(db_path):
    from bot.message_handler import dispatch_typed_subagents
    mutation = {
        "id": "m1",
        "type": "update_plan_tasks",
        "description": "Set grind_am tasks",
        "anchor_id": "grind_am",
        "date": TODAY,
        "tasks": ["Apply to 3 jobs"],
    }
    subagent_response = json.dumps({
        "op": "update_plan_tasks",
        "anchor_id": "grind_am",
        "date": TODAY,
        "tasks": ["Apply to 3 jobs"],
        "report": "Set grind_am tasks to 1 item.",
    })
    with patch("bot.message_handler.call_claude", return_value=subagent_response):
        reports, chat_messages = dispatch_typed_subagents([mutation], "Do the thing.", db_path)
    assert len(reports) == 1
    assert reports[0] == "Set grind_am tasks to 1 item."
    assert chat_messages == []


def test_dispatch_typed_subagents_chat_captured_not_dispatched(db_path):
    from bot.message_handler import dispatch_typed_subagents
    mutations = [
        {"id": "c1", "type": "chat", "description": "Answer question", "message": "Here's the answer."},
    ]
    with patch("bot.message_handler.call_claude") as mock_claude:
        reports, chat_messages = dispatch_typed_subagents(mutations, "Brief.", db_path)
    mock_claude.assert_not_called()
    assert reports == []
    assert chat_messages == ["Here's the answer."]


def test_dispatch_typed_subagents_routes_patch_mutation(db_path):
    from bot.message_handler import dispatch_typed_subagents
    mutation = {
        "id": "p1",
        "type": "patch_context",
        "description": "Update priority",
        "subject": "Job Applications",
        "old": "Priority 1.",
        "new": "Priority 1 — applying.",
    }
    subagent_response = json.dumps({
        "op": "patch_context",
        "subject": "Job Applications",
        "old": "Priority 1.",
        "new": "Priority 1 — applying.",
        "report": "Updated priority line in Job Applications.",
    })
    with patch("bot.message_handler.call_claude", return_value=subagent_response):
        reports, chat_messages = dispatch_typed_subagents([mutation], "Brief.", db_path)
    assert len(reports) == 1
    assert "Job Applications" in reports[0] or "priority" in reports[0].lower()
    assert chat_messages == []


# ---------------------------------------------------------------------------
# call_satisfaction_eval
# ---------------------------------------------------------------------------

def test_call_satisfaction_eval_satisfied(db_path):
    from bot.message_handler import call_satisfaction_eval
    response = json.dumps({"satisfied": True, "issues": [], "replan_needed": False})
    with patch("bot.message_handler.call_claude", return_value=response):
        result = call_satisfaction_eval(
            "Update grind_am tasks",
            [{"id": "m1", "type": "update_plan_tasks", "description": "Set tasks"}],
            ["Set grind_am tasks to 1 item."],
            db_path,
        )
    assert result["satisfied"] is True
    assert result["replan_needed"] is False
    assert result["issues"] == []


def test_call_satisfaction_eval_not_satisfied(db_path):
    from bot.message_handler import call_satisfaction_eval
    response = json.dumps({
        "satisfied": False,
        "issues": ["grind_am tasks were not updated"],
        "replan_needed": True,
    })
    with patch("bot.message_handler.call_claude", return_value=response):
        result = call_satisfaction_eval("Update grind_am tasks", [], [], db_path)
    assert result["satisfied"] is False
    assert result["replan_needed"] is True
    assert len(result["issues"]) == 1


def test_call_satisfaction_eval_fails_gracefully(db_path):
    """If Claude call raises, satisfaction eval defaults to satisfied=True."""
    from bot.message_handler import call_satisfaction_eval
    with patch("bot.message_handler.call_claude", side_effect=RuntimeError("timeout")):
        result = call_satisfaction_eval("anything", [], [], db_path)
    assert result["satisfied"] is True
    assert result["replan_needed"] is False
