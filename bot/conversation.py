"""SDK conversation loop for Tether v3.

Replaces the orchestrator→meta-eval→subagent pipeline when a native
SDK backend (AnthropicBackend, OpenAIBackend, etc.) is available.

The model sees tool results before deciding the next action, eliminating
the one-shot mutation planning problem of the old claude -p approach.
"""
import asyncio
import json
import logging
from datetime import date
from typing import Callable, Awaitable

from bot.llm import LLMResponse, LLMRouter, ToolCall

logger = logging.getLogger(__name__)

MAX_CONVERSATION_ROUNDS = 10


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

def build_system_prompt(
    anchor_name: str,
    anchor_time: str,
    plan_summary: str,
    context_subjects: list[str],
    session_notes: str | None,
) -> str:
    """Assemble the system prompt from modular sections.

    Stable sections (identity, rules) are cheap to cache.
    Volatile sections (anchor, plan, date) are recomputed each turn
    but kept short so cache misses are inexpensive.
    """
    today = date.today().isoformat()
    sections = []

    # --- Identity + rules (stable) ---
    sections.append(
        "You are Tether, a daily task management assistant. "
        "You help the user stay focused, track their plan, and manage their context. "
        "Be concise and direct. Prefer actions over explanation."
    )

    # --- Current state (volatile) ---
    sections.append(
        f"Today is {today}. Current time block: {anchor_name} (starts {anchor_time})."
    )

    # --- Plan (semi-stable) ---
    if plan_summary:
        sections.append(f"Today's plan:\n{plan_summary}")

    # --- Context index (semi-stable, subjects only — bodies fetched via tools) ---
    if context_subjects:
        subjects_list = "\n".join(f"  - {s}" for s in context_subjects)
        sections.append(
            f"Available context entries (fetch bodies with get_context_entry tool):\n{subjects_list}"
        )

    # --- Session notes (injected when available, replaces raw history) ---
    if session_notes:
        sections.append(f"Session Notes:\n{session_notes}")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Tool result formatting
# ---------------------------------------------------------------------------

def format_tool_result_message(
    tool_call: ToolCall,
    result: dict,
    is_error: bool = False,
) -> dict:
    """Format a tool result as an Anthropic-style tool_result message.

    Anthropic's API expects tool results as a user turn with
    content blocks of type tool_result.
    """
    content_str = result.get("content", str(result))
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": content_str,
                "is_error": is_error,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Core conversation loop
# ---------------------------------------------------------------------------

async def conversation_loop(
    router: LLMRouter,
    role: str,
    messages: list[dict],
    system: str,
    tools: list[dict],
    tool_executor: Callable[[ToolCall], Awaitable[dict]] | None,
    max_rounds: int = MAX_CONVERSATION_ROUNDS,
) -> LLMResponse:
    """Run the tool-use conversation loop until end_turn or max_rounds.

    Each round:
      1. Call router.complete(role=...) with current messages
      2. If stop_reason == "end_turn": return the response
      3. If stop_reason == "tool_use": execute each tool call,
         append assistant message + tool results, loop
    """
    if max_rounds < 1:
        raise ValueError("max_rounds must be >= 1")

    current_messages = list(messages)
    response = None

    for round_num in range(max_rounds):
        logger.info("conversation round %d/%d (%d messages in context)",
                    round_num + 1, max_rounds, len(current_messages))
        response = await router.complete(
            role=role,
            messages=current_messages,
            system=system,
            tools=tools if tools else None,
        )

        if response.stop_reason == "end_turn" or not response.tool_calls:
            logger.info("conversation done after %d rounds (stop=%s)",
                        round_num + 1, response.stop_reason)
            return response

        # Append the assistant's message (with tool_use blocks)
        assistant_content = []
        if response.content:
            assistant_content.append({"type": "text", "text": response.content})
        for tc in response.tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            })
        current_messages.append({"role": "assistant", "content": assistant_content})

        # Execute each tool call and collect results
        tool_result_blocks = []
        for tc in response.tool_calls:
            try:
                if tool_executor:
                    result = await tool_executor(tc)
                else:
                    result = {"ok": False, "content": f"No executor registered for {tc.name}"}
                is_error = not result.get("ok", True)
            except Exception as e:
                logger.warning("Tool %s raised: %s", tc.name, e)
                result = {"ok": False, "content": f"Tool error: {e}"}
                is_error = True

            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result.get("content", str(result)),
                "is_error": is_error,
            })

        current_messages.append({"role": "user", "content": tool_result_blocks})

    # Max rounds reached — return whatever the last response was
    logger.warning("conversation_loop hit max_rounds=%d", max_rounds)
    return response


# ---------------------------------------------------------------------------
# handle_message — top-level entry point
# ---------------------------------------------------------------------------

async def handle_message(
    user_text: str,
    router: LLMRouter,
    db_path: str,
    force_quick: bool = False,
    force_full: bool = False,
    role_quick: str = "classifier",
    role_full: str = "main_agent",
    tools: list[dict] | None = None,
    tool_executor: Callable[[ToolCall], Awaitable[dict]] | None = None,
    anchor_name: str = "General",
    anchor_time: str = "00:00",
    plan_summary: str = "",
    context_subjects: list[str] | None = None,
    session_notes: str | None = None,
    conversation_history: list[dict] | None = None,
) -> str:
    """Route an incoming message through quick or full conversation path.

    Quick path: single router.complete(role=role_quick) call, no tools.
    Full path: conversation_loop() with role=role_full and tools.

    Returns the final text response to send to the user.
    """
    system = build_system_prompt(
        anchor_name=anchor_name,
        anchor_time=anchor_time,
        plan_summary=plan_summary,
        context_subjects=context_subjects or [],
        session_notes=session_notes,
    )

    history = list(conversation_history or [])
    history.append({"role": "user", "content": user_text})

    use_quick = force_quick or (not force_full and _classify_quick(user_text))

    if use_quick:
        response = await router.complete(
            role=role_quick,
            messages=history,
            system=system,
            tools=None,
        )
        return response.content

    # Full path — router resolves role to (vendor, model) and picks the best
    # available backend in the fallback chain (NATIVE → MCP → STRUCTURED).
    response = await conversation_loop(
        router=router,
        role=role_full,
        messages=history,
        system=system,
        tools=tools or [],
        tool_executor=tool_executor,
    )
    return response.content


def _classify_quick(text: str) -> bool:
    """Heuristic quick/full classifier. Phase 3 uses simple rules;
    Phase 7 will replace this with a real Haiku classifier call."""
    text_lower = text.strip().lower()
    # Very short messages or greetings → quick
    if len(text_lower) < 15:
        return True
    quick_patterns = ("hi", "hello", "thanks", "ok", "yes", "no", "sure", "what time")
    return any(text_lower.startswith(p) for p in quick_patterns)
