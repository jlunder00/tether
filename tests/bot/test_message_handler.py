import json
import pytest
import subprocess
from datetime import date
from unittest.mock import patch
from db.schema import init_db
from db.queries import get_anchors, upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry

TODAY = str(date.today())


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_anchor(path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                          "duration_minutes": 120, "flexibility": "locked",
                          "strictness": 4, "color": "#e05c5c", "position": 0})
    upsert_plan(path, TODAY)
    upsert_tasks(path, TODAY, "grind_am", tasks=["Apply to 3 jobs"], notes="ML roles")
    upsert_context_entry(path, "Job Applications", "Priority 1.")
    return path


# --- parse_claude_response ---

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


# --- call_claude timeout ---

def test_call_claude_raises_on_timeout():
    from bot.message_handler import call_claude
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 120)):
        with pytest.raises(RuntimeError, match="took too long"):
            call_claude("some prompt")


# --- classify_and_ack ---

def test_classify_and_ack_returns_dispatches():
    from bot.message_handler import classify_and_ack
    response = json.dumps({
        "ack": "Got it, updating grind block.",
        "dispatches": [{"action": "update_plan", "anchor_id": "grind_am", "subjects": ["Job Applications"]}],
    })
    with patch("bot.message_handler.call_claude", return_value=response):
        result = classify_and_ack("Update my grind tasks",
                                  [{"id": "grind_am", "name": "Grind", "time": "08:00"}],
                                  ["Job Applications"])
    assert result["ack"] == "Got it, updating grind block."
    assert result["dispatches"][0]["action"] == "update_plan"


def test_classify_and_ack_chat_only_null_ack():
    from bot.message_handler import classify_and_ack
    response = json.dumps({
        "ack": None,
        "dispatches": [{"action": "chat", "subjects": ["Job Applications"]}],
    })
    with patch("bot.message_handler.call_claude", return_value=response):
        result = classify_and_ack("What should I do now?", [], ["Job Applications"])
    assert result["ack"] is None


def test_classify_and_ack_fallback_on_invalid_json():
    from bot.message_handler import classify_and_ack
    with patch("bot.message_handler.call_claude", return_value="not json at all"):
        result = classify_and_ack("whatever", [], [])
    assert result["ack"] is None
    assert result["dispatches"] == [{"action": "chat", "subjects": []}]


# --- handle_message: two-phase free text ---

def test_handle_message_chat_only_no_ack(db_path):
    from bot.message_handler import handle_message
    classify_result = json.dumps({
        "ack": None,
        "dispatches": [{"action": "chat", "subjects": ["Job Applications"]}],
    })
    dispatch_result = json.dumps({"message": "Focus on job apps.", "mutations": []})
    sent = []
    call_returns = iter([classify_result, dispatch_result])
    with patch("bot.message_handler.call_claude", side_effect=lambda p, **kw: next(call_returns)):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("What should I work on?", sent.append)
    assert sent == ["Focus on job apps."]


def test_handle_message_mutation_sends_ack_first(db_path):
    from bot.message_handler import handle_message
    classify_result = json.dumps({
        "ack": "Got it, updating your grind tasks.",
        "dispatches": [{"action": "update_plan", "anchor_id": "grind_am", "subjects": ["Job Applications"]}],
    })
    dispatch_result = json.dumps({
        "message": "Updated!",
        "mutations": [{"op": "update_plan_tasks", "anchor_id": "grind_am", "tasks": ["Apply to 5 jobs"]}],
    })
    sent = []
    call_returns = iter([classify_result, dispatch_result])
    with patch("bot.message_handler.call_claude", side_effect=lambda p, **kw: next(call_returns)):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("Update my grind tasks to apply to 5 jobs", sent.append)
    assert sent[0] == "Got it, updating your grind tasks."
    assert sent[1] == "Updated!"


def test_handle_message_multi_dispatch(db_path):
    from bot.message_handler import handle_message
    upsert_anchor(db_path, {"id": "deep_work", "name": "Deep Work", "time": "10:30",
                              "duration_minutes": 120, "flexibility": "flexible",
                              "strictness": 2, "color": "#7c6af7", "position": 1})
    classify_result = json.dumps({
        "ack": "Updating both blocks.",
        "dispatches": [
            {"action": "update_plan", "anchor_id": "grind_am", "subjects": ["Job Applications"]},
            {"action": "update_plan", "anchor_id": "deep_work", "subjects": []},
        ],
    })
    dispatch1 = json.dumps({"message": "Grind updated.", "mutations": []})
    dispatch2 = json.dumps({"message": "Deep work updated.", "mutations": []})
    sent = []
    call_returns = iter([classify_result, dispatch1, dispatch2])
    with patch("bot.message_handler.call_claude", side_effect=lambda p, **kw: next(call_returns)):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("Update all my blocks for today", sent.append)
    assert sent == ["Updating both blocks.", "Grind updated.", "Deep work updated."]


def test_handle_message_timeout_sends_error(db_path):
    from bot.message_handler import handle_message
    classify_result = json.dumps({
        "ack": "On it.",
        "dispatches": [{"action": "update_plan", "anchor_id": "grind_am", "subjects": []}],
    })
    sent = []
    call_returns = iter([classify_result, RuntimeError("Claude took too long to respond (>120s).")])
    def side_effect(p, **kw):
        val = next(call_returns)
        if isinstance(val, Exception):
            raise val
        return val
    with patch("bot.message_handler.call_claude", side_effect=side_effect):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("Do a thing", sent.append)
    assert any("took too long" in m for m in sent)


# --- handle_message: slash commands ---

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
    from db.queries import get_context_entries
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


# --- targeted context loading ---

def test_build_dispatch_prompt_targeted_subjects(db_path):
    from bot.message_handler import _build_dispatch_prompt
    dispatch = {"action": "update_plan", "anchor_id": "grind_am", "subjects": ["Job Applications"]}
    prompt = _build_dispatch_prompt("Update my tasks", db_path, dispatch, ack=None)
    assert "Job Applications" in prompt
    assert "Priority 1." in prompt


def test_build_dispatch_prompt_no_subjects_loads_top_level(db_path):
    upsert_context_entry(db_path, "Intellipat", "Startup context.")
    upsert_context_entry(db_path, "Intellipat/Backend", "Should NOT appear.")
    from bot.message_handler import _build_dispatch_prompt
    dispatch = {"action": "chat", "subjects": []}
    prompt = _build_dispatch_prompt("Hello", db_path, dispatch, ack=None)
    assert "Intellipat/Backend" not in prompt
    assert "Intellipat" in prompt
