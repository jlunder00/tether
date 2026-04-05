"""Integration test: full session lifecycle without mocking SDK internals."""
import asyncio
import pytest
import unittest.mock as mock
from pathlib import Path
from db.schema import init_db
from db.queries import get_active_session


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    init_db(p)
    return p


class TestSessionLifecycleIntegration:
    def test_full_session_create_send_close(self, db):
        """Create session → send messages → agent signals done → session closes."""
        from bot.session import SessionManager, Session

        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        with mock.patch.object(Session, "start", new_callable=mock.AsyncMock) as mock_start, \
             mock.patch.object(Session, "send", new_callable=mock.AsyncMock) as mock_send, \
             mock.patch.object(Session, "close", new_callable=mock.AsyncMock):

            mock_start.return_value = "I need to check your tasks. What areas should I focus on?"
            mock_send.return_value = "Got it. I've reorganized your schedule."

            # Turn 1: User sends complex request — no session exists yet, start() is called
            r1 = mgr.run_in_session(
                chat_id="123",
                message="organize my tasks for the week",
                model="claude-sonnet-4-6",
                system_prompt="You are a task assistant.",
            )
            assert "check your tasks" in r1
            assert get_active_session(db, "123") is not None

            # Turn 2: User answers clarification; agent signals done as side effect.
            # We simulate the agent calling session_done tool by setting _is_done on the
            # session object during the send() call — this is what happens in real
            # _send_sdk/_send_backend via _check_done_signal().
            async def send_and_signal_done(msg):
                session = mgr._sessions.get("123")
                if session:
                    session._is_done = True
                    session._done_summary = "Reorganized 15 tasks across 5 anchors"
                return "Got it. I've reorganized your schedule."

            mock_send.side_effect = send_and_signal_done

            r2 = mgr.run_in_session(
                chat_id="123",
                message="focus on work and thesis",
                model="claude-sonnet-4-6",
                system_prompt="You are a task assistant.",
            )
            assert "reorganized" in r2

            # Session should be closed now — done signal was detected in run_in_session
            assert mgr.get_session("123") is None

    def test_turn_limit_closes_session(self, db):
        """Session auto-closes when max_turns is reached."""
        from bot.session import SessionManager, Session

        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        with mock.patch.object(Session, "start", new_callable=mock.AsyncMock) as mock_start, \
             mock.patch.object(Session, "send", new_callable=mock.AsyncMock) as mock_send, \
             mock.patch.object(Session, "close", new_callable=mock.AsyncMock):

            # Turn 1: start() is called (no session yet). Simulate the turn count increment
            # that real start()/send() would do.
            async def start_and_count(msg):
                session = mgr._sessions.get("123")
                if session:
                    session._is_active = True
                    session._turn_count += 1
                return "Turn 1"

            async def send_and_count(msg):
                session = mgr._sessions.get("123")
                if session:
                    session._turn_count += 1
                return "Turn 2"

            mock_start.side_effect = start_and_count
            mock_send.side_effect = send_and_count

            # Turn 1: start session with max_turns=2
            mgr.run_in_session(
                chat_id="123", message="go",
                model="m", system_prompt="s", max_turns=2,
            )
            assert mgr.get_session("123") is not None

            # Turn 2: turn_count reaches max_turns=2 → at_turn_limit becomes True
            result = mgr.run_in_session(
                chat_id="123", message="more",
                model="m", system_prompt="s", max_turns=2,
            )
            # Should include turn limit message appended by run_in_session
            assert "turn limit" in result.lower() or "session ended" in result.lower()
            # Session should be gone
            assert mgr.get_session("123") is None

    def test_new_message_after_closed_session_creates_new(self, db):
        """After a session closes, the next message starts fresh."""
        from bot.session import SessionManager, Session

        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        with mock.patch.object(Session, "start", new_callable=mock.AsyncMock) as mock_start, \
             mock.patch.object(Session, "send", new_callable=mock.AsyncMock), \
             mock.patch.object(Session, "close", new_callable=mock.AsyncMock):

            mock_start.return_value = "Session 1"

            # Start and close a session
            mgr.run_in_session(chat_id="123", message="task 1", model="m", system_prompt="s")
            mgr.close_session("123", summary="Done")
            assert mgr.get_session("123") is None

            # New message should create new session
            mock_start.return_value = "Session 2"
            r = mgr.run_in_session(chat_id="123", message="new task", model="m", system_prompt="s")
            assert r == "Session 2"
            assert mock_start.call_count == 2  # Called twice = two sessions
