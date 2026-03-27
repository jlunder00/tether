import json
import pytest
from datetime import date
from unittest.mock import patch
from pathlib import Path
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


def test_handle_message_calls_claude_and_returns_text(db_path):
    from bot.message_handler import handle_message
    response = json.dumps({"message": "Focus on job apps.", "mutations": []})
    with patch("bot.message_handler.call_claude", return_value=response) as mock_claude:
        with patch("bot.message_handler.DB_PATH", db_path):
            result = handle_message("Hello, what should I do?")
    mock_claude.assert_called_once()
    assert result == "Focus on job apps."


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


def test_handle_message_applies_anchor_mutation(db_path):
    from bot.message_handler import handle_message
    response = json.dumps({
        "message": "Moved grind block to 9am.",
        "mutations": [{"op": "update_anchor", "anchor_id": "grind_am", "time": "09:00"}],
    })
    with patch("bot.message_handler.call_claude", return_value=response):
        with patch("bot.message_handler.DB_PATH", db_path):
            result = handle_message("Move my grind block to 9am")
    assert result == "Moved grind block to 9am."
    anchors = {a["id"]: a for a in get_anchors(db_path)}
    assert anchors["grind_am"]["time"] == "09:00"


def test_handle_check_in_inserts_db_row(db_path):
    from bot.message_handler import handle_message
    from db.queries import get_plan
    with patch("bot.message_handler.call_claude", return_value="Great progress!"):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("/check-in applied to 2 jobs :: about to start third")
    plan = get_plan(db_path, TODAY)
    assert len(plan["check_in_log"]) == 1
    assert plan["check_in_log"][0]["accomplished"] == "applied to 2 jobs"


def test_handle_update_context_saves_to_db(db_path):
    from bot.message_handler import handle_message
    from db.queries import get_context_entries
    with patch("bot.message_handler.call_claude", return_value="Got it."):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("/tether-update-context Thesis :: Working on chapter 3")
    entries = get_context_entries(db_path)
    assert any(e["subject"] == "Thesis" for e in entries)


def test_handle_update_plan_saves_tasks(db_path):
    from bot.message_handler import handle_message
    from db.queries import get_plan
    with patch("bot.message_handler.call_claude", return_value="Updated!"):
        with patch("bot.message_handler.DB_PATH", db_path):
            handle_message("/update-plan grind_am :: New task 1; New task 2")
    plan = get_plan(db_path, TODAY)
    assert plan["anchors"]["grind_am"]["tasks"] == ["New task 1", "New task 2"]
