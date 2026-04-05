import pytest
import unittest.mock as mock
from pathlib import Path
from db.schema import init_db


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    init_db(p)
    return p


_FAKE_CONFIG = {
    "llm": {
        "roles": {
            "main_agent": {"model": "claude-sonnet-4-6"},
        },
        "mcp_server_url": "http://localhost:5001/sse",
    },
}


class TestV3SessionRouting:
    def test_handle_v3_session_calls_session_manager(self, db):
        from bot.message_handler import _handle_v3_session

        with (
            mock.patch("bot.message_handler._get_session_manager") as mock_get_mgr,
            mock.patch("bot.message_handler.load_config", return_value=_FAKE_CONFIG),
            mock.patch("bot.conversation.build_system_prompt", return_value="system prompt"),
            mock.patch("bot.memory.read_session_notes", return_value=None),
        ):
            mock_mgr = mock.MagicMock()
            mock_mgr.run_in_session.return_value = "Here's my analysis..."
            mock_mgr.cleanup_stale.return_value = []
            mock_get_mgr.return_value = mock_mgr

            result = _handle_v3_session(
                text="organize all my tasks",
                db_path=db,
                anchors=[],
                current_anchor={"name": "General", "time": "00:00", "id": "general"},
            )

        assert result == "Here's my analysis..."
        mock_mgr.run_in_session.assert_called_once()
        mock_mgr.cleanup_stale.assert_called_once()

    def test_handle_v3_session_passes_system_prompt(self, db):
        from bot.message_handler import _handle_v3_session

        with (
            mock.patch("bot.message_handler._get_session_manager") as mock_get_mgr,
            mock.patch("bot.message_handler.load_config", return_value=_FAKE_CONFIG),
            mock.patch("bot.conversation.build_system_prompt", return_value="system prompt"),
            mock.patch("bot.memory.read_session_notes", return_value=None),
        ):
            mock_mgr = mock.MagicMock()
            mock_mgr.run_in_session.return_value = "ok"
            mock_mgr.cleanup_stale.return_value = []
            mock_get_mgr.return_value = mock_mgr

            _handle_v3_session(
                text="test",
                db_path=db,
                anchors=[],
                current_anchor={"name": "Deep Work", "time": "09:00", "id": "deep_work"},
            )

        call_kwargs = mock_mgr.run_in_session.call_args
        # system_prompt should be passed as a keyword arg
        assert "system_prompt" in call_kwargs.kwargs or len(call_kwargs.args) >= 4
