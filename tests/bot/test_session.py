"""Tests for bot.session — backend-agnostic multi-turn Session class."""
import asyncio
import pytest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from bot.llm import LLMResponse, ToolCall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(**overrides):
    """Create a Session with sensible defaults, merging in overrides."""
    from bot.session import Session

    defaults = dict(
        session_id="test-123",
        chat_id="456",
        model="claude-sonnet-4-6",
        system_prompt="You are a task assistant.",
        max_turns=10,
    )
    defaults.update(overrides)
    return Session(**defaults)


def _mock_router(content="OK", tool_calls=None, stop_reason="end_turn"):
    """Return a MagicMock LLMBackend whose complete() returns a canned LLMResponse."""
    backend = MagicMock()
    backend.complete = AsyncMock(return_value=LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,
        input_tokens=100,
        output_tokens=50,
    ))
    return backend


# ===========================================================================
# Construction & properties
# ===========================================================================

class TestSessionInit:
    def test_created_with_correct_state(self):
        session = _make_session(mcp_server_url="http://localhost:5001/sse")
        assert session.session_id == "test-123"
        assert session.chat_id == "456"
        assert session.turn_count == 0
        assert session.max_turns == 10
        assert session.is_active is False
        assert session.is_done is False
        assert session.messages == []

    def test_turn_limit_detection(self):
        session = _make_session(max_turns=3)
        assert session.at_turn_limit is False
        session._turn_count = 3
        assert session.at_turn_limit is True

    def test_mode_reports_router_when_no_client(self):
        session = _make_session(router=_mock_router())
        assert session.mode == "router"

    def test_mode_reports_sdk_when_client_set(self):
        session = _make_session()
        session._client = MagicMock()  # simulate SDK connection
        assert session.mode == "sdk"

    def test_build_options(self):
        """Verify ClaudeAgentOptions are built correctly for SDK mode."""
        session = _make_session(mcp_server_url="http://localhost:5001/sse")
        options = session._build_options()
        assert options.model == "claude-sonnet-4-6"
        assert options.permission_mode == "bypassPermissions"
        assert options.mcp_servers.get("tether", {}).get("type") == "sse"
        assert "ToolSearch" in (options.allowed_tools or [])


# ===========================================================================
# SDK mode — send/receive
# ===========================================================================

class TestSessionSDKMode:
    """Test the SDK transport path using mocked ClaudeSDKClient."""

    def test_send_increments_turn_count(self):
        session = _make_session()

        mock_client = MagicMock()
        mock_client.query = AsyncMock()

        async def fake_receive():
            from claude_agent_sdk import ResultMessage
            yield ResultMessage(
                subtype="success",
                duration_ms=100,
                duration_api_ms=90,
                is_error=False,
                num_turns=1,
                session_id="test-123",
                stop_reason="end_turn",
                total_cost_usd=0.01,
            )

        mock_client.receive_response = fake_receive
        session._client = mock_client
        session._is_active = True

        response = asyncio.run(session.send("hello"))
        assert session.turn_count == 1
        assert response is not None

    def test_send_collects_text_from_assistant_message(self):
        """Text blocks from AssistantMessage are concatenated."""
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        session = _make_session(session_id="test-456", chat_id="789")

        mock_client = MagicMock()
        mock_client.query = AsyncMock()

        async def fake_receive():
            yield AssistantMessage(
                content=[TextBlock(text="Hello "), TextBlock(text="world!")],
                model="claude-sonnet-4-6",
            )
            yield ResultMessage(
                subtype="success", duration_ms=100, duration_api_ms=90,
                is_error=False, num_turns=1, session_id="test-456",
                stop_reason="end_turn", total_cost_usd=0.01,
            )

        mock_client.receive_response = fake_receive
        session._client = mock_client
        session._is_active = True

        response = asyncio.run(session.send("hi"))
        assert response == "Hello world!"

    def test_send_appends_to_message_history(self):
        """Both user and assistant messages land in the history."""
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        session = _make_session()
        mock_client = MagicMock()
        mock_client.query = AsyncMock()

        async def fake_receive():
            yield AssistantMessage(
                content=[TextBlock(text="Got it.")],
                model="claude-sonnet-4-6",
            )
            yield ResultMessage(
                subtype="success", duration_ms=50, duration_api_ms=40,
                is_error=False, num_turns=1, session_id="test-123",
                stop_reason="end_turn", total_cost_usd=0.001,
            )

        mock_client.receive_response = fake_receive
        session._client = mock_client
        session._is_active = True

        asyncio.run(session.send("do the thing"))

        msgs = session.messages
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "do the thing"}
        assert msgs[1] == {"role": "assistant", "content": "Got it."}


# ===========================================================================
# Backend mode — send via LLMBackend + conversation_loop
# ===========================================================================

class TestSessionRouterMode:
    """Test the router transport path using mocked LLMRouter."""

    def test_send_increments_turn_count(self):
        router = _mock_router(content="Here you go.")
        session = _make_session(router=router)
        session._is_active = True

        response = asyncio.run(session.send("hello"))
        assert session.turn_count == 1
        assert response == "Here you go."

    def test_send_appends_to_message_history(self):
        router = _mock_router(content="Done.")
        session = _make_session(router=router)
        session._is_active = True

        asyncio.run(session.send("update my plan"))

        msgs = session.messages
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "update my plan"}
        assert msgs[1] == {"role": "assistant", "content": "Done."}

    def test_multi_turn_history_accumulates(self):
        """Each turn adds to the same messages list."""
        router = _mock_router(content="Turn response.")
        session = _make_session(router=router, max_turns=5)
        session._is_active = True

        asyncio.run(session.send("first"))
        asyncio.run(session.send("second"))

        assert session.turn_count == 2
        msgs = session.messages
        assert len(msgs) == 4  # 2 user + 2 assistant
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "user"
        assert msgs[3]["role"] == "assistant"

    def test_done_signal_from_tool_call(self):
        """Session detects session_done in backend mode tool calls."""
        router = _mock_router(
            content="All done.",
            tool_calls=[ToolCall(
                id="tc_1",
                name="mcp__tether__session_done",
                input={"summary": "Organized tasks."},
            )],
        )
        session = _make_session(router=router)
        session._is_active = True

        asyncio.run(session.send("wrap up"))
        assert session.is_done is True
        assert session.done_summary == "Organized tasks."

    def test_backend_passes_full_history(self):
        """conversation_loop receives the accumulated messages."""
        router = _mock_router(content="Acknowledged.")
        session = _make_session(router=router)
        session._is_active = True

        asyncio.run(session.send("first message"))
        asyncio.run(session.send("second message"))

        # The second call to conversation_loop should receive 3 messages:
        # user "first message", assistant "Acknowledged.", user "second message"
        # (conversation_loop is called with a copy of _messages)
        last_call_args = router.complete.call_args
        messages_sent = last_call_args.kwargs.get("messages", last_call_args[1].get("messages", []))
        assert len(messages_sent) == 3

    def test_start_activates_and_sends(self):
        """start() sets is_active=True and delegates to send()."""
        router = _mock_router(content="Welcome!")
        session = _make_session(router=router)

        response = asyncio.run(session.start("hi there"))
        assert session.is_active is True
        assert session.turn_count == 1
        assert response == "Welcome!"


# ===========================================================================
# Error handling
# ===========================================================================

class TestSessionErrors:
    def test_send_raises_when_not_active(self):
        session = _make_session()
        with pytest.raises(RuntimeError, match="Session not active"):
            asyncio.run(session.send("hello"))

    def test_send_raises_at_turn_limit(self):
        session = _make_session(max_turns=3)
        session._is_active = True
        session._client = MagicMock()
        session._turn_count = 3

        with pytest.raises(RuntimeError, match="turn limit reached"):
            asyncio.run(session.send("hello"))

    def test_send_raises_without_transport(self):
        """Active session with neither client nor backend raises."""
        session = _make_session()
        session._is_active = True

        with pytest.raises(RuntimeError, match="no transport"):
            asyncio.run(session.send("hello"))


# ===========================================================================
# Done signal detection
# ===========================================================================

class TestDoneSignal:
    def test_session_done_detected(self):
        session = _make_session()
        session._check_done_signal(
            "mcp__tether__session_done",
            {"summary": "All tasks organized."},
        )
        assert session.is_done is True
        assert session.done_summary == "All tasks organized."

    def test_other_tools_ignored(self):
        session = _make_session()
        session._check_done_signal("mcp__tether__update_context_entry", {"subject": "foo"})
        assert session.is_done is False
        assert session.done_summary is None


# ===========================================================================
# Close / cleanup
# ===========================================================================

class TestSessionClose:
    def test_close_sets_inactive(self):
        session = _make_session()
        session._is_active = True
        mock_client = MagicMock()
        mock_client.disconnect = AsyncMock()
        session._client = mock_client

        asyncio.run(session.close())
        assert session.is_active is False
        mock_client.disconnect.assert_called_once()

    def test_close_handles_disconnect_error(self):
        """Close should not raise even if disconnect fails."""
        session = _make_session()
        session._is_active = True
        mock_client = MagicMock()
        mock_client.disconnect = AsyncMock(side_effect=ConnectionError("gone"))
        session._client = mock_client

        asyncio.run(session.close())
        assert session.is_active is False

    def test_close_without_client(self):
        """Close works when no client was ever created (backend mode)."""
        session = _make_session(router=_mock_router())
        session._is_active = True

        asyncio.run(session.close())
        assert session.is_active is False

    def test_close_idempotent(self):
        """Closing an already-inactive session is a no-op."""
        session = _make_session()
        asyncio.run(session.close())
        assert session.is_active is False


# ===========================================================================
# SessionManager
# ===========================================================================

class TestSessionManager:
    def test_create_session(self, tmp_path):
        from bot.session import SessionManager
        from db.schema import init_db

        db = tmp_path / "test.db"
        init_db(db)
        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        session = mgr.create_session(
            chat_id="123",
            model="claude-sonnet-4-6",
            system_prompt="test",
        )
        assert session.chat_id == "123"
        assert session.session_id is not None

    def test_get_session(self, tmp_path):
        from bot.session import SessionManager
        from db.schema import init_db

        db = tmp_path / "test.db"
        init_db(db)
        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        session = mgr.create_session(
            chat_id="123",
            model="claude-sonnet-4-6",
            system_prompt="test",
        )
        retrieved = mgr.get_session("123")
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    def test_get_session_returns_none_when_no_active(self, tmp_path):
        from bot.session import SessionManager
        from db.schema import init_db

        db = tmp_path / "test.db"
        init_db(db)
        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        assert mgr.get_session("999") is None

    def test_close_session(self, tmp_path):
        from bot.session import SessionManager
        from db.schema import init_db

        db = tmp_path / "test.db"
        init_db(db)
        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        session = mgr.create_session(
            chat_id="123",
            model="claude-sonnet-4-6",
            system_prompt="test",
        )
        mgr.close_session("123", summary="Done")
        assert mgr.get_session("123") is None

    def test_run_in_session_creates_if_needed(self, tmp_path):
        """run_in_session creates a new session when none exists."""
        from bot.session import SessionManager
        from db.schema import init_db

        db = tmp_path / "test.db"
        init_db(db)
        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        with mock.patch("bot.session.Session.start", new_callable=mock.AsyncMock, return_value="Hello!"):
            response = mgr.run_in_session(
                chat_id="123",
                message="organize my tasks",
                model="claude-sonnet-4-6",
                system_prompt="test",
            )
        assert response == "Hello!"

    def test_run_in_session_reuses_existing(self, tmp_path):
        """run_in_session sends to existing session when one is active."""
        from bot.session import SessionManager
        from db.schema import init_db

        db = tmp_path / "test.db"
        init_db(db)
        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        with mock.patch("bot.session.Session.start", new_callable=mock.AsyncMock, return_value="Turn 1"):
            mgr.run_in_session(
                chat_id="123",
                message="organize my tasks",
                model="claude-sonnet-4-6",
                system_prompt="test",
            )

        with mock.patch("bot.session.Session.send", new_callable=mock.AsyncMock, return_value="Turn 2"):
            response = mgr.run_in_session(
                chat_id="123",
                message="yes, do it",
                model="claude-sonnet-4-6",
                system_prompt="test",
            )
        assert response == "Turn 2"


# ===========================================================================
# Stale session cleanup
# ===========================================================================

class TestSessionMemoryManagement:
    def test_close_with_summary_appends_to_notes(self, tmp_path):
        from bot.session import SessionManager
        from db.schema import init_db

        db = tmp_path / "test.db"
        init_db(db)
        notes_path = tmp_path / ".session-notes.md"

        mgr = SessionManager(db_path=str(db), mcp_server_url=None)
        session = mgr.create_session(chat_id="123", model="m", system_prompt="s")
        session._turn_count = 3  # Simulate some turns

        with mock.patch("bot.session.Path.home", return_value=tmp_path):
            # Create the .tether-config dir structure
            (tmp_path / ".tether-config").mkdir(exist_ok=True)
            mgr.close_session("123", summary="Organized 15 tasks")

        notes = (tmp_path / ".tether-config" / ".session-notes.md").read_text()
        assert "Organized 15 tasks" in notes
        assert session.session_id[:8] in notes

    def test_close_without_summary_skips_memory(self, tmp_path):
        from bot.session import SessionManager
        from db.schema import init_db

        db = tmp_path / "test.db"
        init_db(db)
        mgr = SessionManager(db_path=str(db), mcp_server_url=None)
        mgr.create_session(chat_id="123", model="m", system_prompt="s")
        mgr.close_session("123")  # No summary
        # No crash, no notes file needed


class TestStaleCleanup:
    def test_cleanup_stale_closes_timed_out_sessions(self, tmp_path):
        from bot.session import SessionManager
        from db.schema import init_db
        from db.queries import get_db, create_session

        db = tmp_path / "test.db"
        init_db(db)
        sid = create_session(db, chat_id="123", max_turns=10)

        with get_db(db) as conn:
            conn.execute(
                "UPDATE sessions SET last_activity = datetime('now', '-20 minutes') WHERE id = ?",
                (sid,),
            )

        mgr = SessionManager(db_path=str(db), mcp_server_url=None)
        closed = mgr.cleanup_stale()
        assert sid in closed
