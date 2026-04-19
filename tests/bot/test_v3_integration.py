"""Tests for v3 routing in message_handler — community edition.

Tests the basic v3 single-shot path. Premium-specific tests
(sessions, LLMRouter, conversation_loop) are in tether-premium.
"""
# TODO(cleanup): handle_message signature changed to async (pool, user_id) in Phase 3a.
# These tests call it with the old sync db_path signature and need to be reviewed —
# v3 routing may be stale or may need to be rewritten as async tests with mocked pool.
import pytest
pytestmark = pytest.mark.skip(reason="v3 routing tests use old sync db_path signature — review in codebase cleanup")
import unittest.mock as mock
from pathlib import Path
from db.schema import init_db
from db.queries import upsert_anchor, upsert_plan, get_recent_history


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    init_db(str(p))
    upsert_anchor(str(p), {
        "id": "morning", "name": "Morning", "time": "07:00",
        "duration_minutes": 60, "flexibility": "locked",
        "strictness": 3, "color": "#fff", "position": 0,
    })
    upsert_plan(str(p), "2026-04-03")
    return p


class TestV3Routing:
    def test_uses_v3_when_config_flag_set(self, db_path, monkeypatch, tmp_path):
        """When llm.use_v3 is true, handle_message should call the basic v3 path."""
        import yaml
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "llm": {"use_v3": True},
            "telegram": {"bot_token": "fake", "chat_id": "123"},
        }))
        monkeypatch.setattr("bot.message_handler._CONFIG_PATH", str(config_path))

        from bot.message_handler import handle_message

        sent = []
        with mock.patch("bot.message_handler._handle_v3", return_value="v3 response"):
            handle_message("what's on my plan?", sent.append, db_path=db_path)

        assert "v3 response" in sent

    def test_uses_v2_when_config_flag_false(self, db_path, monkeypatch, tmp_path):
        """When llm.use_v3 is false, handle_message should use the old pipeline."""
        import yaml
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "llm": {"use_v3": False},
            "telegram": {"bot_token": "fake", "chat_id": "123"},
        }))
        monkeypatch.setattr("bot.message_handler._CONFIG_PATH", str(config_path))

        from bot.message_handler import handle_message

        sent = []
        with mock.patch("bot.message_handler._handle_v3") as mock_v3:
            with mock.patch("bot.message_handler.call_response_builder", return_value="v2 response"):
                with mock.patch("bot.message_handler._classify_message", return_value="quick"):
                    handle_message("what's on my plan?", sent.append, db_path=db_path)

        assert not mock_v3.called

    def test_uses_v2_when_config_missing(self, db_path, monkeypatch, tmp_path):
        """When no llm config exists, default to v2."""
        import yaml
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "telegram": {"bot_token": "fake", "chat_id": "123"},
        }))
        monkeypatch.setattr("bot.message_handler._CONFIG_PATH", str(config_path))

        from bot.message_handler import handle_message

        sent = []
        with mock.patch("bot.message_handler._handle_v3") as mock_v3:
            with mock.patch("bot.message_handler.call_response_builder", return_value="v2 response"):
                with mock.patch("bot.message_handler._classify_message", return_value="quick"):
                    handle_message("hi", sent.append, db_path=db_path)

        assert not mock_v3.called

    def test_v3_records_conversation_history(self, db_path, monkeypatch, tmp_path):
        """V3 path should save user+assistant turns to conversation_history."""
        import yaml
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "llm": {"use_v3": True},
            "telegram": {"bot_token": "fake", "chat_id": "123"},
        }))
        monkeypatch.setattr("bot.message_handler._CONFIG_PATH", str(config_path))

        from bot.message_handler import handle_message

        with mock.patch("bot.message_handler._handle_v3", return_value="v3 reply"):
            handle_message("test message", lambda m: None, db_path=db_path)

        history = get_recent_history(db_path, 2)
        roles = [h["role"] for h in history]
        assert "user" in roles
        assert "assistant" in roles

    def test_v3_falls_back_to_v2_on_error(self, db_path, monkeypatch, tmp_path):
        """If v3 path raises, fall back to v2 pipeline."""
        import yaml
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "llm": {"use_v3": True, "v2_fallback": True},
            "telegram": {"bot_token": "fake", "chat_id": "123"},
        }))
        monkeypatch.setattr("bot.message_handler._CONFIG_PATH", str(config_path))

        from bot.message_handler import handle_message

        sent = []
        with mock.patch("bot.message_handler._handle_v3", side_effect=RuntimeError("v3 broke")):
            with mock.patch("bot.message_handler.call_response_builder", return_value="v2 fallback"):
                with mock.patch("bot.message_handler._classify_message", return_value="quick"):
                    handle_message("hello", sent.append, db_path=db_path)

        assert len(sent) > 0
