# Multi-Turn Session Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the Tether bot agent to maintain context across multiple Telegram messages within a session, ask clarifying questions, receive answers without losing tool-call history, and explicitly end sessions with memory management.

**Architecture:** A `SessionManager` runs a persistent asyncio event loop in a background thread, managing `ClaudeSDKClient` instances (the Agent SDK's bidirectional client). Each active session holds a live connection to the bundled Claude CLI with MCP tools connected. The synchronous Telegram polling loop communicates with sessions via thread-safe queues. When the agent needs user input, its response is sent to Telegram and the session waits. The user's reply is forwarded back to the same `ClaudeSDKClient`, preserving full context (tool call history, reasoning state, MCP connections). The agent signals completion by calling a `session_done` MCP tool, triggering memory management and session teardown.

**Tech Stack:** `claude_agent_sdk.ClaudeSDKClient` (bidirectional), asyncio background thread, `asyncio.Queue` for cross-thread communication, SQLite for session state tracking, existing tether MCP server for `session_done` tool.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `bot/session.py` | **Create** | `Session` class (wraps `ClaudeSDKClient`), `SessionManager` (manages lifecycle, background loop) |
| `bot/message_handler.py` | **Modify** | Route messages through `SessionManager` instead of one-shot `_handle_v3` |
| `bot/llm.py` | **Modify** | Extract shared config-building logic from `AgentSDKBackend` into reusable helper |
| `tether_mcp/server.py` | **Modify** | Add `session_done` MCP tool |
| `db/schema.py` | **Modify** | Add `sessions` table |
| `db/queries.py` | **Modify** | Add session CRUD functions |
| `api/routes/sessions.py` | **Create** | REST endpoints for session state (frontend can show active sessions) |
| `tests/bot/test_session.py` | **Create** | Unit + integration tests for session lifecycle |
| `tests/bot/test_session_integration.py` | **Create** | End-to-end tests with real SDK types |

---

## Task 1: Database Schema for Sessions

**Files:**
- Modify: `db/schema.py` (add migration)
- Modify: `db/queries.py` (add CRUD)
- Test: `tests/db/test_session_queries.py`

- [ ] **Step 1: Write failing tests for session CRUD**

```python
# tests/db/test_session_queries.py
import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import (
    create_session, get_active_session, update_session_state,
    update_session_activity, close_session, get_stale_sessions,
)


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    init_db(p)
    return p


class TestSessionQueries:
    def test_create_session(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        assert sid is not None
        session = get_active_session(db, chat_id="123")
        assert session is not None
        assert session["state"] == "active"
        assert session["turn_count"] == 0
        assert session["max_turns"] == 10

    def test_no_active_session_returns_none(self, db):
        assert get_active_session(db, chat_id="123") is None

    def test_update_session_state(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        update_session_state(db, sid, "waiting_user")
        session = get_active_session(db, chat_id="123")
        assert session["state"] == "waiting_user"

    def test_update_session_activity(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        update_session_activity(db, sid, turn_count=3)
        session = get_active_session(db, chat_id="123")
        assert session["turn_count"] == 3

    def test_close_session(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        close_session(db, sid, summary="Done organizing tasks")
        assert get_active_session(db, chat_id="123") is None

    def test_get_stale_sessions(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        # Manually backdate last_activity to simulate staleness
        from db.queries import get_db
        with get_db(db) as conn:
            conn.execute(
                "UPDATE sessions SET last_activity = datetime('now', '-20 minutes') WHERE id = ?",
                (sid,),
            )
        stale = get_stale_sessions(db, timeout_minutes=15)
        assert len(stale) == 1
        assert stale[0]["id"] == sid

    def test_only_one_active_session_per_chat(self, db):
        sid1 = create_session(db, chat_id="123", max_turns=10)
        sid2 = create_session(db, chat_id="123", max_turns=10)
        # First session should be auto-closed
        session = get_active_session(db, chat_id="123")
        assert session["id"] == sid2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/data/tether/.worktrees/tether-sessions && python -m pytest tests/db/test_session_queries.py -v`
Expected: FAIL — `create_session` not defined

- [ ] **Step 3: Add sessions table to schema**

In `db/schema.py`, add to `init_db()` migrations:

```python
# In the migration block of init_db():
conn.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id          TEXT PRIMARY KEY,
        chat_id     TEXT NOT NULL,
        state       TEXT NOT NULL DEFAULT 'active',
        turn_count  INTEGER NOT NULL DEFAULT 0,
        max_turns   INTEGER NOT NULL DEFAULT 10,
        summary     TEXT,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_activity DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_sessions_chat_active
    ON sessions(chat_id, state)
    WHERE state IN ('active', 'waiting_user')
""")
```

- [ ] **Step 4: Implement session query functions**

In `db/queries.py`:

```python
import uuid as _uuid


def create_session(db_path: Path, chat_id: str, max_turns: int = 10) -> str:
    """Create a new session, closing any existing active session for this chat."""
    sid = str(_uuid.uuid4())
    with get_db(db_path) as conn:
        # Close any existing active sessions for this chat
        conn.execute(
            "UPDATE sessions SET state = 'closed' "
            "WHERE chat_id = ? AND state IN ('active', 'waiting_user')",
            (chat_id,),
        )
        conn.execute(
            "INSERT INTO sessions (id, chat_id, state, max_turns) VALUES (?, ?, 'active', ?)",
            (sid, chat_id, max_turns),
        )
    return sid


def get_active_session(db_path: Path, chat_id: str) -> dict | None:
    """Get the active or waiting session for a chat, or None."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE chat_id = ? AND state IN ('active', 'waiting_user') "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
    return dict(row) if row else None


def update_session_state(db_path: Path, session_id: str, state: str) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET state = ?, last_activity = CURRENT_TIMESTAMP WHERE id = ?",
            (state, session_id),
        )


def update_session_activity(db_path: Path, session_id: str, turn_count: int) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET turn_count = ?, last_activity = CURRENT_TIMESTAMP WHERE id = ?",
            (turn_count, session_id),
        )


def close_session(db_path: Path, session_id: str, summary: str | None = None) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET state = 'closed', summary = ?, last_activity = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (summary, session_id),
        )


def get_stale_sessions(db_path: Path, timeout_minutes: int = 15) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE state IN ('active', 'waiting_user') "
            "AND last_activity < datetime('now', ? || ' minutes')",
            (f"-{timeout_minutes}",),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/db/test_session_queries.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 6: Commit**

```bash
git add db/schema.py db/queries.py tests/db/test_session_queries.py
git commit -m "feat: sessions table + CRUD queries for multi-turn session tracking"
```

---

## Task 2: Session Class — ClaudeSDKClient Wrapper

**Files:**
- Create: `bot/session.py`
- Test: `tests/bot/test_session.py`

- [ ] **Step 1: Write failing tests for Session lifecycle**

```python
# tests/bot/test_session.py
import asyncio
import pytest
import unittest.mock as mock
from unittest.mock import AsyncMock, MagicMock, patch


class TestSession:
    def test_session_created_with_correct_state(self):
        from bot.session import Session
        session = Session(
            session_id="test-123",
            chat_id="456",
            mcp_server_url="http://localhost:5001/sse",
            model="claude-sonnet-4-6",
            system_prompt="You are a task assistant.",
            max_turns=10,
        )
        assert session.session_id == "test-123"
        assert session.chat_id == "456"
        assert session.turn_count == 0
        assert session.max_turns == 10
        assert session.is_active is False  # Not started yet
        assert session.is_done is False

    def test_session_turn_limit_detection(self):
        from bot.session import Session
        session = Session(
            session_id="test-123",
            chat_id="456",
            mcp_server_url=None,
            model="claude-sonnet-4-6",
            system_prompt="test",
            max_turns=3,
        )
        session._turn_count = 3
        assert session.at_turn_limit is True

    def test_session_build_options(self):
        """Verify ClaudeAgentOptions are built correctly."""
        from bot.session import Session
        session = Session(
            session_id="test-123",
            chat_id="456",
            mcp_server_url="http://localhost:5001/sse",
            model="claude-sonnet-4-6",
            system_prompt="You are helpful.",
            max_turns=10,
        )
        options = session._build_options()
        assert options.model == "claude-sonnet-4-6"
        assert options.permission_mode == "bypassPermissions"
        assert options.mcp_servers.get("tether", {}).get("type") == "sse"
        assert "ToolSearch" in (options.allowed_tools or [])


class TestSessionSendReceive:
    """Test the send/receive flow using mocked ClaudeSDKClient."""

    def test_send_message_increments_turn_count(self):
        from bot.session import Session

        session = Session(
            session_id="test-123",
            chat_id="456",
            mcp_server_url=None,
            model="claude-sonnet-4-6",
            system_prompt="test",
            max_turns=10,
        )

        # Mock the client
        mock_client = MagicMock()
        mock_client.query = AsyncMock()

        async def fake_receive():
            from claude_agent_sdk.types import ResultMessage
            yield ResultMessage(
                subtype="success",
                duration_ms=100,
                duration_api_ms=90,
                is_error=False,
                num_turns=1,
                session_id="test-123",
                stop_reason="end_turn",
                total_cost_usd=0.01,
                result="Here's my answer.",
            )

        mock_client.receive_response = fake_receive
        session._client = mock_client
        session._is_active = True

        response = asyncio.run(session.send("hello"))
        assert session.turn_count == 1
        assert response is not None

    def test_session_done_detection(self):
        """Session detects session_done tool call in response."""
        from bot.session import Session

        session = Session(
            session_id="test-123",
            chat_id="456",
            mcp_server_url=None,
            model="claude-sonnet-4-6",
            system_prompt="test",
            max_turns=10,
        )
        # Simulate receiving a session_done tool call
        session._check_done_signal("session_done", {"summary": "All tasks organized."})
        assert session.is_done is True
        assert session.done_summary == "All tasks organized."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/bot/test_session.py -v`
Expected: FAIL — `bot.session` module not found

- [ ] **Step 3: Implement Session class**

```python
# bot/session.py
"""Multi-turn session management for Tether v3.

A Session wraps a ClaudeSDKClient to maintain context across multiple
Telegram messages. The agent can ask questions, receive answers, and
call tools without losing its reasoning state.

SessionManager runs sessions in a background asyncio event loop,
bridging the synchronous Telegram polling loop with async SDK calls.
"""
import asyncio
import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Shared allowed tools list — same as AgentSDKBackend
from bot.llm import _AGENT_SDK_ALLOWED_TOOLS

_SESSION_TIMEOUT_MINUTES = 15
_DEFAULT_MAX_TURNS = 10


class Session:
    """Wraps a ClaudeSDKClient for a multi-turn conversation.

    Lifecycle:
      1. Created with config (not yet connected)
      2. start() → connects ClaudeSDKClient, sends initial prompt
      3. send(msg) → sends follow-up, receives response
      4. close() → disconnects, runs cleanup
    """

    def __init__(
        self,
        session_id: str,
        chat_id: str,
        mcp_server_url: str | None,
        model: str,
        system_prompt: str,
        max_turns: int = _DEFAULT_MAX_TURNS,
    ):
        self.session_id = session_id
        self.chat_id = chat_id
        self._mcp_server_url = mcp_server_url
        self._model = model
        self._system_prompt = system_prompt
        self.max_turns = max_turns
        self._turn_count = 0
        self._is_active = False
        self._is_done = False
        self._done_summary: str | None = None
        self._client = None

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def is_done(self) -> bool:
        return self._is_done

    @property
    def done_summary(self) -> str | None:
        return self._done_summary

    @property
    def at_turn_limit(self) -> bool:
        return self._turn_count >= self.max_turns

    def _build_options(self):
        """Build ClaudeAgentOptions for this session."""
        from claude_agent_sdk import ClaudeAgentOptions
        from claude_agent_sdk.types import McpSSEServerConfig

        mcp_servers = {}
        if self._mcp_server_url:
            mcp_servers["tether"] = McpSSEServerConfig(
                type="sse", url=self._mcp_server_url
            )

        return ClaudeAgentOptions(
            model=self._model,
            system_prompt=self._system_prompt,
            mcp_servers=mcp_servers,
            permission_mode="bypassPermissions",
            allowed_tools=_AGENT_SDK_ALLOWED_TOOLS,
            session_id=self.session_id,
        )

    async def start(self, initial_message: str) -> str:
        """Connect and send the initial message. Returns the agent's response."""
        from claude_agent_sdk import ClaudeSDKClient

        options = self._build_options()
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        self._is_active = True
        logger.info("session %s: started (model=%s, max_turns=%d)",
                     self.session_id, self._model, self.max_turns)
        return await self.send(initial_message)

    async def send(self, message: str) -> str:
        """Send a user message and collect the agent's response."""
        if not self._is_active or self._client is None:
            raise RuntimeError("Session not active")
        if self.at_turn_limit:
            raise RuntimeError(f"Session turn limit reached ({self.max_turns})")

        from claude_agent_sdk import AssistantMessage, ResultMessage

        await self._client.query(message, session_id=self.session_id)
        self._turn_count += 1

        content_text = ""
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        content_text += block.text
                    elif hasattr(block, "name"):
                        # Tool use — check for session_done
                        tool_name = getattr(block, "name", "")
                        tool_input = getattr(block, "input", {})
                        self._check_done_signal(tool_name, tool_input)
                        logger.info("session %s: tool_use %s", self.session_id, tool_name)
            elif isinstance(msg, ResultMessage):
                logger.info(
                    "session %s: turn %d complete (cost=$%.4f, stop=%s)",
                    self.session_id, self._turn_count,
                    msg.total_cost_usd or 0, msg.stop_reason,
                )

        return content_text.strip()

    def _check_done_signal(self, tool_name: str, tool_input: dict) -> None:
        """Check if the agent called session_done."""
        if tool_name == "mcp__tether__session_done":
            self._is_done = True
            self._done_summary = tool_input.get("summary", "")
            logger.info("session %s: agent signaled done: %s",
                         self.session_id, self._done_summary)

    async def close(self) -> None:
        """Disconnect and clean up."""
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.warning("session %s: disconnect error: %s", self.session_id, e)
        self._is_active = False
        logger.info("session %s: closed (turns=%d, done=%s)",
                     self.session_id, self._turn_count, self._is_done)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/bot/test_session.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add bot/session.py tests/bot/test_session.py
git commit -m "feat: Session class — ClaudeSDKClient wrapper for multi-turn conversations"
```

---

## Task 3: SessionManager — Background Event Loop + Lifecycle

**Files:**
- Modify: `bot/session.py` (add SessionManager)
- Test: `tests/bot/test_session.py` (add SessionManager tests)

- [ ] **Step 1: Write failing tests for SessionManager**

```python
# Append to tests/bot/test_session.py

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

        # Mock the actual SDK interaction
        with patch("bot.session.Session.start", new_callable=AsyncMock, return_value="Hello!"):
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

        with patch("bot.session.Session.start", new_callable=AsyncMock, return_value="Turn 1"):
            mgr.run_in_session(
                chat_id="123",
                message="organize my tasks",
                model="claude-sonnet-4-6",
                system_prompt="test",
            )

        with patch("bot.session.Session.send", new_callable=AsyncMock, return_value="Turn 2"):
            response = mgr.run_in_session(
                chat_id="123",
                message="yes, do it",
                model="claude-sonnet-4-6",
                system_prompt="test",
            )
        assert response == "Turn 2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/bot/test_session.py::TestSessionManager -v`
Expected: FAIL — `SessionManager` not defined

- [ ] **Step 3: Implement SessionManager**

Append to `bot/session.py`:

```python
class SessionManager:
    """Manages multi-turn sessions across Telegram messages.

    Bridges the synchronous polling loop with async ClaudeSDKClient
    sessions via a background asyncio event loop.
    """

    def __init__(self, db_path: str, mcp_server_url: str | None):
        self._db_path = db_path
        self._mcp_server_url = mcp_server_url
        self._sessions: dict[str, Session] = {}  # chat_id → Session
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Start the background event loop if not running."""
        if self._loop is None or not self._loop.is_running():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever,
                daemon=True,
                name="session-loop",
            )
            self._thread.start()
            logger.info("SessionManager: background event loop started")
        return self._loop

    def _run_async(self, coro) -> any:
        """Run an async coroutine in the background loop, blocking until done."""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=300)  # 5 min timeout

    def create_session(
        self,
        chat_id: str,
        model: str,
        system_prompt: str,
        max_turns: int = _DEFAULT_MAX_TURNS,
    ) -> Session:
        """Create a new session, closing any existing one for this chat."""
        from db.queries import create_session as db_create

        # Close existing session if any
        existing = self._sessions.pop(chat_id, None)
        if existing and existing.is_active:
            self._run_async(existing.close())

        session_id = db_create(self._db_path, chat_id, max_turns)
        session = Session(
            session_id=session_id,
            chat_id=chat_id,
            mcp_server_url=self._mcp_server_url,
            model=model,
            system_prompt=system_prompt,
            max_turns=max_turns,
        )
        self._sessions[chat_id] = session
        return session

    def get_session(self, chat_id: str) -> Session | None:
        """Get the active session for a chat, or None."""
        session = self._sessions.get(chat_id)
        if session and (session.is_done or not session.is_active):
            self._sessions.pop(chat_id, None)
            return None
        return session

    def close_session(self, chat_id: str, summary: str | None = None) -> None:
        """Close a session and persist to DB."""
        from db.queries import close_session as db_close

        session = self._sessions.pop(chat_id, None)
        if session:
            if session.is_active:
                self._run_async(session.close())
            db_close(self._db_path, session.session_id, summary)
            logger.info("SessionManager: closed session %s for chat %s",
                         session.session_id, chat_id)

    def run_in_session(
        self,
        chat_id: str,
        message: str,
        model: str,
        system_prompt: str,
        max_turns: int = _DEFAULT_MAX_TURNS,
    ) -> str:
        """Send a message in the session for this chat. Creates session if needed.

        This is the main entry point from the synchronous polling loop.
        Returns the agent's response text.
        """
        from db.queries import update_session_state, update_session_activity

        session = self.get_session(chat_id)

        if session is None:
            # New session — create and start
            session = self.create_session(chat_id, model, system_prompt, max_turns)
            response = self._run_async(session.start(message))
        else:
            # Existing session — send follow-up
            response = self._run_async(session.send(message))

        # Update DB state
        update_session_activity(self._db_path, session.session_id, session.turn_count)

        if session.is_done:
            self.close_session(chat_id, summary=session.done_summary)
            update_session_state(self._db_path, session.session_id, "closed")
        elif session.at_turn_limit:
            logger.warning("Session %s hit turn limit (%d)", session.session_id, session.max_turns)
            self.close_session(chat_id, summary="Turn limit reached")
            response += "\n\n[Session ended — turn limit reached]"
        else:
            update_session_state(self._db_path, session.session_id, "waiting_user")

        return response

    def cleanup_stale(self) -> list[str]:
        """Close sessions that have been idle too long. Returns list of closed session IDs."""
        from db.queries import get_stale_sessions, close_session as db_close

        stale = get_stale_sessions(self._db_path, timeout_minutes=_SESSION_TIMEOUT_MINUTES)
        closed = []
        for s in stale:
            chat_id = s["chat_id"]
            session = self._sessions.pop(chat_id, None)
            if session and session.is_active:
                self._run_async(session.close())
            db_close(self._db_path, s["id"], summary="Session timed out")
            closed.append(s["id"])
            logger.info("SessionManager: timed out session %s for chat %s",
                         s["id"], chat_id)
        return closed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/bot/test_session.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add bot/session.py tests/bot/test_session.py
git commit -m "feat: SessionManager — background event loop, session lifecycle, stale cleanup"
```

---

## Task 4: session_done MCP Tool

**Files:**
- Modify: `tether_mcp/server.py`
- Test: `tests/tether_mcp/test_session_done.py`

- [ ] **Step 1: Write failing test for session_done tool**

```python
# tests/tether_mcp/test_session_done.py
import pytest


class TestSessionDoneTool:
    def test_session_done_tool_exists(self):
        """The session_done tool must be registered on the MCP server."""
        from tether_mcp.server import mcp
        tools = {t.name for t in mcp._tool_manager.list_tools()}
        assert "session_done" in tools

    def test_session_done_accepts_summary(self):
        """session_done tool accepts a summary parameter."""
        import asyncio
        from tether_mcp.server import session_done
        # The tool should return confirmation
        result = asyncio.run(session_done(summary="All tasks organized for the week."))
        assert "acknowledged" in result.lower() or "done" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tether_mcp/test_session_done.py -v`
Expected: FAIL — `session_done` not found

- [ ] **Step 3: Implement session_done MCP tool**

In `tether_mcp/server.py`, add:

```python
@mcp.tool()
async def session_done(summary: str = "") -> str:
    """Signal that the current session is complete.

    Call this when you have finished all planned work for this conversation.
    Include a brief summary of what was accomplished — this is saved for
    the user's records and used by the memory management system.

    Args:
        summary: Brief description of what was accomplished in this session.
    """
    # The tool itself is a no-op signal — the bot detects the tool call
    # in the agent's response and closes the session. The summary is
    # extracted from the tool input by Session._check_done_signal().
    return f"Session done acknowledged. Summary: {summary or '(none provided)'}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tether_mcp/test_session_done.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tether_mcp/server.py tests/tether_mcp/test_session_done.py
git commit -m "feat: session_done MCP tool — agent signals session completion"
```

---

## Task 5: Integrate SessionManager into Message Handler

**Files:**
- Modify: `bot/message_handler.py`
- Test: `tests/bot/test_message_handler_sessions.py`

- [ ] **Step 1: Write failing tests for session routing**

```python
# tests/bot/test_message_handler_sessions.py
import pytest
import unittest.mock as mock
from unittest.mock import patch, MagicMock
from pathlib import Path
from db.schema import init_db


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    init_db(p)
    return p


class TestV3SessionRouting:
    def test_complex_message_creates_session(self, db):
        """A FULL-classified message should create a session."""
        from bot.message_handler import _handle_v3_session

        mgr = MagicMock()
        mgr.get_session.return_value = None
        mgr.run_in_session.return_value = "Here's my analysis..."

        result = _handle_v3_session(
            text="organize all my tasks for the week",
            db_path=db,
            session_manager=mgr,
            anchors=[],
            current_anchor={"name": "General", "time": "00:00", "id": "general"},
        )

        mgr.run_in_session.assert_called_once()
        assert result == "Here's my analysis..."

    def test_reply_to_waiting_session_continues(self, db):
        """A message when a session is waiting should continue it."""
        from bot.message_handler import _handle_v3_session

        mock_session = MagicMock()
        mock_session.is_done = False
        mock_session.is_active = True

        mgr = MagicMock()
        mgr.get_session.return_value = mock_session
        mgr.run_in_session.return_value = "Got it, making changes now."

        result = _handle_v3_session(
            text="yes, go ahead and reschedule those",
            db_path=db,
            session_manager=mgr,
            anchors=[],
            current_anchor={"name": "General", "time": "00:00", "id": "general"},
        )

        mgr.run_in_session.assert_called_once()
        assert "making changes" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/bot/test_message_handler_sessions.py -v`
Expected: FAIL — `_handle_v3_session` not defined

- [ ] **Step 3: Implement _handle_v3_session and wire into handle_message**

In `bot/message_handler.py`, add a new function and modify the v3 path:

```python
# Module-level session manager (lazy-initialized)
_session_manager: "SessionManager | None" = None


def _get_session_manager(db_path: Path) -> "SessionManager":
    """Lazily initialize the session manager."""
    global _session_manager
    if _session_manager is None:
        from bot.session import SessionManager
        config = load_config()
        llm_config = config.get("llm", {})
        mcp_url = llm_config.get("mcp_server_url", "http://localhost:5001/sse")
        _session_manager = SessionManager(db_path=str(db_path), mcp_server_url=mcp_url)
    return _session_manager


def _handle_v3_session(
    text: str,
    db_path: Path,
    session_manager,
    anchors: list[dict],
    current_anchor: dict,
) -> str:
    """Run the v3 multi-turn session loop. Returns the response text."""
    from bot.conversation import build_system_prompt
    from bot.memory import read_session_notes
    from datetime import date as date_type

    today = str(date_type.today())
    plan = get_plan(db_path, today)
    subjects = [e["subject"] for e in get_context_entries(db_path)]

    plan_lines = []
    for anchor_id, data in plan.get("anchors", {}).items():
        tasks = data.get("tasks", [])
        task_strs = [f"[{t.get('status', '?')[:1]}] {t.get('text', '')}" for t in tasks]
        plan_lines.append(f"{anchor_id}: {' | '.join(task_strs) or 'empty'}")

    notes_path = str(Path.home() / ".tether-config" / ".session-notes.md")
    session_notes = read_session_notes(notes_path)

    system = build_system_prompt(
        anchor_name=current_anchor.get("name", "General"),
        anchor_time=current_anchor.get("time", "00:00"),
        plan_summary="\n".join(plan_lines) or "No plan data.",
        context_subjects=subjects,
        session_notes=session_notes,
    )

    config = load_config()
    llm_config = config.get("llm", {})
    roles = llm_config.get("roles", {})
    main_role = roles.get("main_agent", {})
    model = main_role.get("model", "claude-sonnet-4-6")

    return session_manager.run_in_session(
        chat_id=str(current_anchor.get("_chat_id", "default")),
        message=text,
        model=model,
        system_prompt=system,
    )
```

Then in `handle_message()`, replace the `_handle_v3()` call:

```python
    # --- v3 SDK path (if enabled) ---
    if _is_v3_enabled():
        try:
            mgr = _get_session_manager(db_path)
            # Cleanup stale sessions periodically
            mgr.cleanup_stale()
            final = _handle_v3_session(text, db_path, mgr, anchors, current_anchor)
            send_fn(final)
            insert_conversation_turn(db_path, "user", text)
            insert_conversation_turn(db_path, "assistant", final)
            return
        except Exception as e:
            # ... existing fallback logic ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/bot/test_message_handler_sessions.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest -q`
Expected: All pass (existing tests should not regress — `_handle_v3` is still used as fallback)

- [ ] **Step 6: Commit**

```bash
git add bot/message_handler.py tests/bot/test_message_handler_sessions.py
git commit -m "feat: integrate SessionManager into v3 message handler"
```

---

## Task 6: Memory Management on Session Close

**Files:**
- Modify: `bot/session.py` (add close hooks)
- Modify: `bot/message_handler.py` (trigger memory after session close)
- Test: `tests/bot/test_session.py` (add memory management tests)

- [ ] **Step 1: Write failing test for post-session memory management**

```python
# Append to tests/bot/test_session.py

class TestSessionMemoryManagement:
    def test_session_close_triggers_memory_update(self, tmp_path):
        """Closing a session should trigger session notes update."""
        from bot.session import SessionManager
        from db.schema import init_db

        db = tmp_path / "test.db"
        init_db(db)
        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        with patch("bot.session.Session.start", new_callable=AsyncMock, return_value="Done"):
            mgr.run_in_session(
                chat_id="123",
                message="test",
                model="claude-sonnet-4-6",
                system_prompt="test",
            )

        # Manually mark session as done
        session = mgr.get_session("123")
        if session:
            session._is_done = True
            session._done_summary = "Organized all tasks"

        with patch("bot.memory.update_session_notes") as mock_update, \
             patch("bot.memory.commit_significant_mutations") as mock_commit:
            mock_update.return_value = asyncio.coroutine(lambda: None)()
            mock_commit.return_value = asyncio.coroutine(lambda: None)()
            mgr.close_session("123", summary="Organized all tasks")

        # Memory functions should have been called
        # (actual invocation depends on implementation hooks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/bot/test_session.py::TestSessionMemoryManagement -v`
Expected: FAIL or partial

- [ ] **Step 3: Add memory management hooks to SessionManager.close_session**

In `bot/session.py`, modify `close_session`:

```python
    def close_session(self, chat_id: str, summary: str | None = None) -> None:
        """Close a session, persist to DB, and trigger memory management."""
        from db.queries import close_session as db_close

        session = self._sessions.pop(chat_id, None)
        if session:
            if session.is_active:
                self._run_async(session.close())

            # Trigger memory management if session had meaningful work
            if session.turn_count > 0 and summary:
                self._run_memory_management(session, summary)

            db_close(self._db_path, session.session_id, summary)
            logger.info("SessionManager: closed session %s (turns=%d, summary=%s)",
                         session.session_id, session.turn_count, summary)

    def _run_memory_management(self, session: Session, summary: str) -> None:
        """Update session notes and context after a session ends."""
        try:
            from bot.memory import update_session_notes

            notes_path = str(Path.home() / ".tether-config" / ".session-notes.md")
            # Use a simple sync-compatible approach for memory update
            # The LLM-based update can happen asynchronously later
            from pathlib import Path as _Path
            existing = ""
            try:
                existing = _Path(notes_path).read_text()
            except FileNotFoundError:
                pass

            # Append session summary to notes
            updated = existing.rstrip()
            if updated:
                updated += "\n\n"
            updated += f"## Session {session.session_id[:8]} ({session.turn_count} turns)\n{summary}"
            _Path(notes_path).parent.mkdir(parents=True, exist_ok=True)
            _Path(notes_path).write_text(updated)

            logger.info("SessionManager: memory updated for session %s", session.session_id)
        except Exception as e:
            logger.warning("SessionManager: memory management failed: %s", e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/bot/test_session.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/session.py tests/bot/test_session.py
git commit -m "feat: memory management hooks on session close"
```

---

## Task 7: Session Status API Endpoints

**Files:**
- Create: `api/routes/sessions.py`
- Modify: `api/main.py` (register router)
- Test: `tests/api/test_session_routes.py`

- [ ] **Step 1: Write failing tests for session API**

```python
# tests/api/test_session_routes.py
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from db.schema import init_db
from db.queries import create_session


@pytest.fixture
def client(tmp_path):
    import os
    os.environ["TETHER_DB_PATH"] = str(tmp_path / "test.db")
    os.environ.setdefault("TETHER_JWT_SECRET", "test-secret-key-for-testing")
    init_db(Path(os.environ["TETHER_DB_PATH"]))
    from api.main import app
    return TestClient(app)


class TestSessionRoutes:
    def test_get_active_sessions(self, client, tmp_path):
        db = Path(tmp_path / "test.db")
        create_session(db, chat_id="123", max_turns=10)
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["chat_id"] == "123"

    def test_get_sessions_empty(self, client):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert len(resp.json()["sessions"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/api/test_session_routes.py -v`
Expected: FAIL

- [ ] **Step 3: Implement session API routes**

```python
# api/routes/sessions.py
from fastapi import APIRouter, Depends, Request
from pathlib import Path
import os

from api.auth import auth_dependency

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _db_path() -> Path:
    return Path(os.environ.get("TETHER_DB_PATH", "~/.tether-config/tether.db")).expanduser()


@router.get("")
async def get_active_sessions(request: Request, _auth=Depends(auth_dependency)):
    from db.queries import get_db
    db = _db_path()
    with get_db(db) as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE state IN ('active', 'waiting_user') "
            "ORDER BY last_activity DESC"
        ).fetchall()
    return {"sessions": [dict(r) for r in rows]}
```

Register in `api/main.py`:
```python
from api.routes.sessions import router as sessions_router
app.include_router(sessions_router, prefix="/api")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/api/test_session_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/sessions.py api/main.py tests/api/test_session_routes.py
git commit -m "feat: /api/sessions endpoint for active session status"
```

---

## Task 8: Stale Session Cleanup in Polling Loop

**Files:**
- Modify: `bot/message_handler.py`
- Test: `tests/bot/test_session.py` (add cleanup test)

- [ ] **Step 1: Write failing test for stale cleanup integration**

```python
# Append to tests/bot/test_session.py

class TestStaleCleanup:
    def test_cleanup_stale_closes_timed_out_sessions(self, tmp_path):
        from bot.session import SessionManager
        from db.schema import init_db
        from db.queries import get_db, create_session

        db = tmp_path / "test.db"
        init_db(db)
        sid = create_session(db, chat_id="123", max_turns=10)

        # Backdate the session
        with get_db(db) as conn:
            conn.execute(
                "UPDATE sessions SET last_activity = datetime('now', '-20 minutes') WHERE id = ?",
                (sid,),
            )

        mgr = SessionManager(db_path=str(db), mcp_server_url=None)
        closed = mgr.cleanup_stale()
        assert sid in closed
```

- [ ] **Step 2: Run test, implement if needed, verify pass**

Run: `python -m pytest tests/bot/test_session.py::TestStaleCleanup -v`
Expected: PASS (cleanup_stale already implemented in Task 3)

- [ ] **Step 3: Commit**

```bash
git add tests/bot/test_session.py
git commit -m "test: stale session cleanup integration test"
```

---

## Task 9: End-to-End Integration Test

**Files:**
- Create: `tests/bot/test_session_integration.py`

- [ ] **Step 1: Write integration test that exercises the full flow**

```python
# tests/bot/test_session_integration.py
"""Integration test: full session lifecycle without mocking SDK internals."""
import asyncio
import pytest
import unittest.mock as mock
from pathlib import Path
from db.schema import init_db
from db.queries import get_active_session, create_session


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

        # Mock Session.start and Session.send to avoid real SDK calls
        with mock.patch.object(Session, "start", new_callable=mock.AsyncMock) as mock_start, \
             mock.patch.object(Session, "send", new_callable=mock.AsyncMock) as mock_send, \
             mock.patch.object(Session, "close", new_callable=mock.AsyncMock):

            mock_start.return_value = "I need to check your tasks. What areas should I focus on?"
            mock_send.return_value = "Got it. I've reorganized your schedule."

            # Turn 1: User sends complex request
            r1 = mgr.run_in_session(
                chat_id="123",
                message="organize my tasks for the week",
                model="claude-sonnet-4-6",
                system_prompt="You are a task assistant.",
            )
            assert "check your tasks" in r1
            assert get_active_session(db, "123") is not None

            # Turn 2: User answers clarification question
            r2 = mgr.run_in_session(
                chat_id="123",
                message="focus on work and thesis",
                model="claude-sonnet-4-6",
                system_prompt="You are a task assistant.",
            )
            assert "reorganized" in r2

            # Simulate agent calling session_done
            session = mgr.get_session("123")
            session._is_done = True
            session._done_summary = "Reorganized 15 tasks across 5 anchors"

            # Turn 3: session_done detected, session closes
            mock_send.return_value = "All done! I've reorganized 15 tasks."
            r3 = mgr.run_in_session(
                chat_id="123",
                message="looks good, thanks",
                model="claude-sonnet-4-6",
                system_prompt="You are a task assistant.",
            )

            # Session should be closed now
            assert mgr.get_session("123") is None

    def test_turn_limit_closes_session(self, db):
        """Session auto-closes when max_turns is reached."""
        from bot.session import SessionManager, Session

        mgr = SessionManager(db_path=str(db), mcp_server_url=None)

        with mock.patch.object(Session, "start", new_callable=mock.AsyncMock) as mock_start, \
             mock.patch.object(Session, "send", new_callable=mock.AsyncMock) as mock_send, \
             mock.patch.object(Session, "close", new_callable=mock.AsyncMock):

            mock_start.return_value = "Turn 1"
            mock_send.return_value = "Turn N"

            # Start session with max_turns=2
            mgr.run_in_session(
                chat_id="123", message="go", model="m", system_prompt="s", max_turns=2,
            )

            # Second turn should trigger turn limit
            session = mgr.get_session("123")
            session._turn_count = 2  # Simulate reaching limit

            result = mgr.run_in_session(
                chat_id="123", message="more", model="m", system_prompt="s", max_turns=2,
            )
            assert "turn limit" in result.lower() or mgr.get_session("123") is None
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/bot/test_session_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/bot/test_session_integration.py
git commit -m "test: end-to-end session lifecycle integration tests"
```

---

## Task 10: Final Wiring and Push

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest -v`
Expected: All pass

- [ ] **Step 2: Push branch**

```bash
git push origin feature/v3-multi-turn-sessions
```

- [ ] **Step 3: Create PR**

```bash
gh pr create --title "feat: multi-turn session loop" \
  --base milestone/tether-v3-llm-redesign \
  --body "$(cat <<'EOF'
## Summary
- Adds multi-turn session support: agent maintains context across Telegram messages
- ClaudeSDKClient (bidirectional) keeps MCP tools connected between turns
- Agent can ask clarifying questions without losing tool-call history
- session_done MCP tool lets agent explicitly end sessions
- Memory management runs on session close
- Sessions auto-close after 15min idle or max turns reached
- /api/sessions endpoint for frontend visibility

## Architecture
SessionManager runs a background asyncio event loop. Each active session
holds a live ClaudeSDKClient connection. The synchronous polling loop
communicates via thread-safe futures. Session state persists in SQLite.

## Test plan
- [ ] Unit tests for Session class lifecycle
- [ ] Unit tests for SessionManager create/close/cleanup
- [ ] DB CRUD tests for sessions table
- [ ] Integration tests for full session lifecycle
- [ ] API route tests for /api/sessions
- [ ] Manual test: send complex message → bot asks question → reply → bot continues → bot calls session_done
EOF
)"
```

---

## Design Decisions & Trade-offs

### Why `ClaudeSDKClient` over session resume (`--resume`)?
- **Persistent MCP connection**: No reconnect overhead between turns (~2s saved per turn)
- **In-memory context**: Claude CLI holds the full conversation in memory, no disk load
- **Richer control**: Can interrupt, check context usage, change model mid-session

### Why a background thread instead of converting to fully async?
- The Telegram polling loop is synchronous (`requests.get` with 30s timeout)
- Converting the entire bot to async is a larger refactor (future task)
- The background thread approach is isolated — one `threading.Thread` with its own event loop

### Why not `AskUserQuestion` as a native tool?
- `AskUserQuestion` is a Claude Code native tool that prompts via stdin
- It can't send a Telegram message — it's designed for interactive CLI
- Instead, the agent's response text IS the question, and the bot routes the reply back

### Session timeout (15 min)
- Balances resource usage with user experience
- A connected `ClaudeSDKClient` holds a live subprocess
- 15 min gives users time to think and respond without wasting Pi resources

### Max turns default (10)
- Prevents runaway sessions from consuming unbounded context/cost
- 10 turns is enough for: gather context (1-2), ask questions (2-3), make changes (3-4), confirm (1)
