"""Multi-turn session management for Tether v3.

A Session maintains conversation state across multiple Telegram messages,
regardless of which LLM backend is used to produce responses.

Two transport modes:

  1. **SDK mode** — a ClaudeSDKClient handles bidirectional streaming.
     The SDK maintains its own server-side context; we still track
     history locally for DB persistence and done-signal detection.

  2. **Backend mode** — any LLMBackend (Anthropic API, OpenAI, Bedrock,
     claude -p) is used via conversation_loop(). The Session owns the
     full messages list and replays it each turn so the model sees the
     complete conversation.

SessionManager (Task 3) will run sessions in a background asyncio event
loop, bridging the synchronous Telegram polling loop with async calls.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Callable, Awaitable

from bot.llm import LLMBackend, LLMResponse, LLMRouter, ToolCall, _AGENT_SDK_ALLOWED_TOOLS

if TYPE_CHECKING:
    from bot.tools.base import Tool

logger = logging.getLogger(__name__)

_SESSION_TIMEOUT_MINUTES = 15
_DEFAULT_MAX_TURNS = 10


class Session:
    """Multi-turn conversation session, backend-agnostic.

    Lifecycle:
      1. Created with config (not yet active)
      2. start(initial_message) -> activates, sends first message, returns response
      3. send(msg) -> sends follow-up, returns response
      4. close() -> cleans up transport, marks inactive

    The same Session object tracks turn count, done state, and message
    history whether the underlying transport is ClaudeSDKClient or a
    plain LLMBackend.
    """

    def __init__(
        self,
        session_id: str,
        chat_id: str,
        model: str,
        system_prompt: str,
        *,
        mcp_server_url: str | None = None,
        backend: LLMBackend | None = None,
        tools: list[dict] | None = None,
        tool_executor: Callable[[ToolCall], Awaitable[dict]] | None = None,
        max_turns: int = _DEFAULT_MAX_TURNS,
    ):
        self.session_id = session_id
        self.chat_id = chat_id
        self._model = model
        self._system_prompt = system_prompt
        self._mcp_server_url = mcp_server_url
        self._backend = backend
        self._tools = tools or []
        self._tool_executor = tool_executor
        self.max_turns = max_turns

        # State
        self._turn_count = 0
        self._is_active = False
        self._is_done = False
        self._done_summary: str | None = None
        self._messages: list[dict] = []

        # SDK transport (None when using backend mode)
        self._client = None

    # -- Properties ----------------------------------------------------------

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

    @property
    def messages(self) -> list[dict]:
        """The full conversation history for this session (read-only copy)."""
        return list(self._messages)

    @property
    def mode(self) -> str:
        """Which transport is in use: 'sdk' or 'backend'."""
        return "sdk" if self._client is not None else "backend"

    # -- SDK helpers ---------------------------------------------------------

    def _build_options(self):
        """Build ClaudeAgentOptions for SDK mode."""
        from claude_agent_sdk import ClaudeAgentOptions
        from claude_agent_sdk.types import McpSSEServerConfig

        mcp_servers = {}
        if self._mcp_server_url:
            mcp_servers["tether"] = McpSSEServerConfig(
                type="sse", url=self._mcp_server_url,
            )

        return ClaudeAgentOptions(
            model=self._model,
            system_prompt=self._system_prompt,
            mcp_servers=mcp_servers,
            permission_mode="bypassPermissions",
            allowed_tools=_AGENT_SDK_ALLOWED_TOOLS,
            session_id=self.session_id,
        )

    # -- Lifecycle -----------------------------------------------------------

    async def start(self, initial_message: str) -> str:
        """Activate the session and send the initial message.

        If a backend was provided at construction, uses backend mode.
        Otherwise, attempts to connect a ClaudeSDKClient (SDK mode).
        Returns the agent's first response.
        """
        if self._backend is not None:
            # Backend mode — no persistent connection needed
            self._is_active = True
            logger.info(
                "session %s: started in backend mode (model=%s, max_turns=%d)",
                self.session_id, self._model, self.max_turns,
            )
        else:
            # SDK mode — establish bidirectional connection
            from claude_agent_sdk import ClaudeSDKClient

            options = self._build_options()
            self._client = ClaudeSDKClient(options=options)
            await self._client.connect()
            self._is_active = True
            logger.info(
                "session %s: started in SDK mode (model=%s, max_turns=%d)",
                self.session_id, self._model, self.max_turns,
            )

        return await self.send(initial_message)

    async def send(self, message: str) -> str:
        """Send a user message and collect the agent's response.

        Dispatches to SDK or backend mode based on how the session was
        started. In both cases, the message history and turn count are
        updated consistently.
        """
        if not self._is_active:
            raise RuntimeError("Session not active")
        if self.at_turn_limit:
            raise RuntimeError(f"Session turn limit reached ({self.max_turns})")

        self._messages.append({"role": "user", "content": message})
        self._turn_count += 1

        if self._client is not None:
            response_text = await self._send_sdk(message)
        elif self._backend is not None:
            response_text = await self._send_backend(message)
        else:
            raise RuntimeError("Session has no transport (no SDK client or backend)")

        self._messages.append({"role": "assistant", "content": response_text})
        return response_text

    async def _send_sdk(self, message: str) -> str:
        """Send via ClaudeSDKClient bidirectional protocol."""
        from claude_agent_sdk import AssistantMessage, ResultMessage

        await self._client.query(message, session_id=self.session_id)

        content_text = ""
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        content_text += block.text
                    elif hasattr(block, "name"):
                        tool_name = getattr(block, "name", "")
                        tool_input = getattr(block, "input", {})
                        self._check_done_signal(tool_name, tool_input)
                        logger.info(
                            "session %s: tool_use %s",
                            self.session_id, tool_name,
                        )
            elif isinstance(msg, ResultMessage):
                logger.info(
                    "session %s: turn %d complete (cost=$%.4f, stop=%s)",
                    self.session_id, self._turn_count,
                    msg.total_cost_usd or 0, msg.stop_reason,
                )

        return content_text.strip()

    async def _send_backend(self, message: str) -> str:
        """Send via LLMBackend with local history management.

        Uses conversation_loop() to handle multi-round tool use within
        a single user turn. The full message history is passed so the
        model sees the entire session context.
        """
        from bot.conversation import conversation_loop

        response = await conversation_loop(
            backend=self._backend,
            messages=list(self._messages),  # copy — loop appends internally
            system=self._system_prompt,
            model=self._model,
            tools=self._tools,
            tool_executor=self._tool_executor,
        )

        # Check tool calls for done signal
        for tc in response.tool_calls:
            self._check_done_signal(tc.name, tc.input)

        return response.content.strip()

    # -- Done detection ------------------------------------------------------

    def _check_done_signal(self, tool_name: str, tool_input: dict) -> None:
        """Check if the agent called session_done."""
        if tool_name == "mcp__tether__session_done":
            self._is_done = True
            self._done_summary = tool_input.get("summary", "")
            logger.info(
                "session %s: agent signaled done: %s",
                self.session_id, self._done_summary,
            )

    # -- Cleanup -------------------------------------------------------------

    async def close(self) -> None:
        """Disconnect transport and mark inactive."""
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.warning(
                    "session %s: disconnect error: %s",
                    self.session_id, e,
                )
            self._client = None
        self._is_active = False
        logger.info(
            "session %s: closed (turns=%d, done=%s, mode=%s)",
            self.session_id, self._turn_count, self._is_done, self.mode,
        )


class SessionManager:
    """Manages multi-turn sessions across Telegram messages.

    Bridges the synchronous polling loop with async ClaudeSDKClient
    sessions via a background asyncio event loop.
    """

    def __init__(self, db_path: str, mcp_server_url: str | None):
        self._db_path = db_path
        self._mcp_server_url = mcp_server_url
        self._sessions: dict[str, Session] = {}  # chat_id -> Session
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

    def _run_async(self, coro):
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
        if session is None:
            return None
        # Evict sessions that are done or that were started then closed
        if session.is_done or (session.turn_count > 0 and not session.is_active):
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
            session = self.create_session(chat_id, model, system_prompt, max_turns)
            response = self._run_async(session.start(message))
        else:
            response = self._run_async(session.send(message))

        # Update DB state
        update_session_activity(self._db_path, session.session_id, session.turn_count)

        if session.is_done:
            self.close_session(chat_id, summary=session.done_summary)
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
