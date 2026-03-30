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
# think_and_plan
# ---------------------------------------------------------------------------

def test_think_and_plan_returns_dispatches(db_path):
    from bot.message_handler import think_and_plan
    response = json.dumps({
        "ack": "Got it, updating grind block.",
        "dispatches": [{"action": "update_plan", "anchor_id": "grind_am",
                        "subjects": ["Job Applications"], "instructions": "Set tasks to X, Y."}],
    })
    with patch("bot.message_handler.call_claude", return_value=response):
        result = think_and_plan("Update my grind tasks",
                                [ANCHOR], ["Job Applications"], db_path)
    assert result["ack"] == "Got it, updating grind block."
    assert result["dispatches"][0]["action"] == "update_plan"


def test_think_and_plan_chat_only_null_ack(db_path):
    from bot.message_handler import think_and_plan
    response = json.dumps({
        "ack": None,
        "dispatches": [{"action": "chat", "subjects": ["Job Applications"], "instructions": ""}],
    })
    with patch("bot.message_handler.call_claude", return_value=response):
        result = think_and_plan("What should I do now?", [ANCHOR], ["Job Applications"], db_path)
    assert result["ack"] is None


def test_think_and_plan_fallback_on_invalid_json(db_path):
    from bot.message_handler import think_and_plan
    with patch("bot.message_handler.call_claude", return_value="not json at all"):
        result = think_and_plan("whatever", [ANCHOR], [], db_path)
    assert result["ack"] is None
    assert result["dispatches"] == [{"action": "chat", "subjects": [], "instructions": ""}]


def test_think_and_plan_includes_plan_in_prompt(db_path):
    from bot.message_handler import think_and_plan
    captured = []
    def capture(prompt, **kw):
        captured.append(prompt)
        return json.dumps({"ack": None, "dispatches": [{"action": "chat", "subjects": [], "instructions": ""}]})
    with patch("bot.message_handler.call_claude", side_effect=capture):
        think_and_plan("Move my tasks", [ANCHOR], ["Job Applications"], db_path)
    assert "Apply to 3 jobs" in captured[0]


# ---------------------------------------------------------------------------
# _execute_dispatch
# ---------------------------------------------------------------------------

def test_execute_dispatch_returns_report(db_path):
    from bot.message_handler import _execute_dispatch
    dispatch_result = json.dumps({
        "report": "Set grind_am tasks to: Apply to 5 jobs.",
        "mutations": [{"op": "update_plan_tasks", "anchor_id": "grind_am", "tasks": ["Apply to 5 jobs"]}],
    })
    with patch("bot.message_handler.call_claude", return_value=dispatch_result):
        result = _execute_dispatch(
            {"action": "update_plan", "anchor_id": "grind_am", "subjects": [], "instructions": "Set to 5 jobs."},
            "Update grind tasks", db_path,
        )
    assert result["report"] == "Set grind_am tasks to: Apply to 5 jobs."
    from db.queries import get_plan
    plan = get_plan(db_path, TODAY)
    assert plan["anchors"]["grind_am"]["tasks"] == ["Apply to 5 jobs"]


def test_execute_dispatch_returns_failed_on_timeout(db_path):
    from bot.message_handler import _execute_dispatch
    with patch("bot.message_handler.call_claude", side_effect=RuntimeError("timed out")):
        result = _execute_dispatch({"action": "chat", "subjects": []}, "hi", db_path)
    assert result["report"].startswith("FAILED:")
    assert result["mutations"] == []


# ---------------------------------------------------------------------------
# _orchestrate — full pipeline
# ---------------------------------------------------------------------------

def test_orchestrate_chat_only_single_final_message(db_path):
    from bot.message_handler import _orchestrate
    dispatches = [{"action": "chat", "subjects": ["Job Applications"], "instructions": ""}]
    dispatch_result = json.dumps({"report": "Told user to focus on jobs.", "mutations": []})
    eval_result = json.dumps({"complete": True, "remaining_dispatches": [], "assessment": "Done."})
    memory_result = json.dumps({"memory_dispatches": []})
    final_result = json.dumps({"message": "Focus on job apps.", "mutations": []})
    sent = []
    call_returns = iter([dispatch_result, eval_result, memory_result, final_result])
    with patch("bot.message_handler.call_claude", side_effect=lambda p, **kw: next(call_returns)):
        with patch("bot.message_handler.DB_PATH", db_path):
            _orchestrate("What should I do?", dispatches, None, db_path, sent.append)
    # No ack for chat-only, one final message
    assert sent == ["Focus on job apps."]


def test_orchestrate_mutation_sends_ack_then_final(db_path):
    from bot.message_handler import _orchestrate
    dispatches = [{"action": "update_plan", "anchor_id": "grind_am", "subjects": [], "instructions": ""}]
    dispatch_result = json.dumps({"report": "Updated grind_am.", "mutations": []})
    eval_result = json.dumps({"complete": True, "remaining_dispatches": [], "assessment": "Done."})
    memory_result = json.dumps({"memory_dispatches": []})
    final_result = json.dumps({"message": "All done!", "mutations": []})
    sent = []
    call_returns = iter([dispatch_result, eval_result, memory_result, final_result])
    with patch("bot.message_handler.call_claude", side_effect=lambda p, **kw: next(call_returns)):
        _orchestrate("Update my tasks", dispatches, "Got it, updating.", db_path, sent.append)
    assert sent[0] == "Got it, updating."
    assert sent[-1] == "All done!"


def test_orchestrate_retries_on_incomplete(db_path):
    from bot.message_handler import _orchestrate
    dispatches = [{"action": "update_plan", "anchor_id": "grind_am", "subjects": [], "instructions": ""}]
    dispatch1 = json.dumps({"report": "FAILED: timeout", "mutations": []})
    eval1 = json.dumps({
        "complete": False,
        "remaining_dispatches": [{"action": "update_plan", "anchor_id": "grind_am",
                                   "subjects": [], "instructions": "Retry: set tasks."}],
        "assessment": "grind_am not updated."
    })
    dispatch2 = json.dumps({"report": "Set grind_am tasks.", "mutations": []})
    eval2 = json.dumps({"complete": True, "remaining_dispatches": [], "assessment": "Done."})
    memory_result = json.dumps({"memory_dispatches": []})
    final_result = json.dumps({"message": "Done after retry.", "mutations": []})
    sent = []
    call_returns = iter([dispatch1, eval1, dispatch2, eval2, memory_result, final_result])
    with patch("bot.message_handler.call_claude", side_effect=lambda p, **kw: next(call_returns)):
        _orchestrate("Update grind tasks", dispatches, "On it.", db_path, sent.append)
    assert "Done after retry." in sent


def test_orchestrate_memory_dispatches_executed(db_path):
    from bot.message_handler import _orchestrate
    dispatches = [{"action": "chat", "subjects": [], "instructions": ""}]
    dispatch_result = json.dumps({"report": "Answered.", "mutations": []})
    eval_result = json.dumps({"complete": True, "remaining_dispatches": [], "assessment": ""})
    memory_result = json.dumps({"memory_dispatches": [
        {"action": "update_context", "subjects": ["Job Applications"],
         "instructions": "Append: Applied to Anthropic."}
    ]})
    mem_dispatch_result = json.dumps({"report": "Appended to Job Applications.", "mutations": []})
    final_result = json.dumps({"message": "Got it!", "mutations": []})
    sent = []
    call_returns = iter([dispatch_result, eval_result, memory_result, mem_dispatch_result, final_result])
    with patch("bot.message_handler.call_claude", side_effect=lambda p, **kw: next(call_returns)):
        _orchestrate("I applied to Anthropic today", dispatches, None, db_path, sent.append)
    assert sent == ["Got it!"]


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
# _build_dispatch_prompt targeted context
# ---------------------------------------------------------------------------

def test_build_dispatch_prompt_targeted_subjects(db_path):
    from bot.message_handler import _build_dispatch_prompt
    dispatch = {"action": "update_plan", "anchor_id": "grind_am",
                "subjects": ["Job Applications"], "instructions": "Set tasks."}
    prompt = _build_dispatch_prompt("Update my tasks", db_path, dispatch)
    assert "Job Applications" in prompt
    assert "Priority 1." in prompt


def test_build_dispatch_prompt_no_subjects_loads_top_level(db_path):
    upsert_context_entry(db_path, "Intellipat", "Startup context.")
    upsert_context_entry(db_path, "Intellipat/Backend", "Should NOT appear.")
    from bot.message_handler import _build_dispatch_prompt
    dispatch = {"action": "chat", "subjects": [], "instructions": ""}
    prompt = _build_dispatch_prompt("Hello", db_path, dispatch)
    assert "Intellipat/Backend" not in prompt
    assert "Intellipat" in prompt


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
# think_and_plan — history injected into prompt
# ---------------------------------------------------------------------------

def test_think_and_plan_history_in_prompt(db_path):
    from bot.message_handler import think_and_plan
    from db.queries import insert_conversation_turn
    insert_conversation_turn(db_path, "user", "Earlier question")
    insert_conversation_turn(db_path, "assistant", "Earlier answer")
    history = [
        {"role": "user",      "body": "Earlier question", "ts": "2026-03-28 10:00:00"},
        {"role": "assistant", "body": "Earlier answer",   "ts": "2026-03-28 10:00:05"},
    ]
    captured = []
    def capture(prompt, **kw):
        captured.append(prompt)
        return '{"ack": null, "dispatches": [{"action": "chat", "subjects": [], "instructions": ""}]}'
    with patch("bot.message_handler.call_claude", side_effect=capture):
        think_and_plan("New question", [ANCHOR], [], db_path, history=history)
    assert "Earlier question" in captured[0]
    assert "Earlier answer" in captured[0]


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
# think_and_plan — request_context type
# ---------------------------------------------------------------------------

def test_think_and_plan_returns_request_context(db_path):
    from bot.message_handler import think_and_plan
    response = json.dumps({
        "type": "request_context",
        "requests": [{"kind": "context_entry", "subject": "Intellipat"}],
        "reason": "Need to read Intellipat before planning.",
    })
    with patch("bot.message_handler.call_claude", return_value=response):
        result = think_and_plan("Update Intellipat context", [ANCHOR], ["Intellipat"], db_path)
    assert result["type"] == "request_context"
    assert result["requests"][0]["subject"] == "Intellipat"


def test_think_and_plan_force_dispatch_overrides_request_context(db_path):
    from bot.message_handler import think_and_plan
    # Even if claude returns request_context, force_dispatch=True should yield dispatch
    response = json.dumps({
        "type": "request_context",
        "requests": [{"kind": "context_entry", "subject": "Intellipat"}],
        "reason": "Still need more context.",
    })
    with patch("bot.message_handler.call_claude", return_value=response):
        result = think_and_plan("whatever", [ANCHOR], [], db_path, force_dispatch=True)
    assert result["type"] == "dispatch"


def test_think_and_plan_accumulated_context_in_prompt(db_path):
    from bot.message_handler import think_and_plan
    captured = []
    def capture(prompt, **kw):
        captured.append(prompt)
        return '{"type": "dispatch", "ack": null, "dispatches": [{"action": "chat", "subjects": [], "instructions": ""}]}'
    with patch("bot.message_handler.call_claude", side_effect=capture):
        think_and_plan(
            "New question", [ANCHOR], [], db_path,
            extra_context=["## Fetched context (round 1)\n### Context: Foo\nFoo body."],
        )
    assert "Foo body." in captured[0]


def test_think_and_plan_rounds_remaining_in_prompt(db_path):
    from bot.message_handler import think_and_plan
    captured = []
    def capture(prompt, **kw):
        captured.append(prompt)
        return '{"type": "dispatch", "ack": null, "dispatches": [{"action": "chat", "subjects": [], "instructions": ""}]}'
    with patch("bot.message_handler.call_claude", side_effect=capture):
        think_and_plan("hi", [ANCHOR], [], db_path, round_num=2)
    # MAX_CONTEXT_ROUNDS=4, round_num=2 → 2 remaining
    assert "2 request round" in captured[0]


# ---------------------------------------------------------------------------
# handle_message — context request loop
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
