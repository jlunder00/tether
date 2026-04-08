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
    mode: str = "scheduler",
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> str:
    """Assemble the system prompt from modular sections.

    Modes control which sections are included:
      - "scheduler": full scheduling + backlog focus (default for FULL path)
      - "coach": brief accountability coaching (for followup nudges)
      - "planner": detailed planning with structured output
      - "quick": minimal prompt for simple responses
      - "followup": followup ping coaching style

    Callers can further customize with include/exclude lists.
    """
    from bot.prompt_sections import build_prompt

    ctx = {
        "today": date.today().isoformat(),
        "anchor_name": anchor_name,
        "anchor_time": anchor_time,
        "plan_summary": plan_summary,
        "context_subjects": context_subjects,
        "session_notes": session_notes,
    }
    return build_prompt(mode=mode, ctx=ctx, include=include, exclude=exclude)


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

    if force_quick:
        use_quick = True
    elif force_full:
        use_quick = False
    else:
        use_quick = await _classify_quick_llm(user_text, router)

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


_CLASSIFIER_SYSTEM = (
    "You are a message router for a task management assistant. "
    "Classify the user's message as QUICK or FULL.\n\n"
    "QUICK: greetings, acknowledgements, simple yes/no, brief conversational replies, "
    "questions answerable from context without fetching live data.\n"
    "FULL: anything requiring task changes, scheduling, planning, organizing, "
    "fetching live plan/task/context/milestone data, multi-step reasoning, or "
    "any request the user wants acted upon in their system.\n\n"
    "Reply with exactly one word: QUICK or FULL."
)


async def _classify_quick_llm(user_text: str, router: LLMRouter) -> bool:
    """Call Haiku to classify the message as quick (True) or full (False).
    Falls back to the heuristic if the classifier call fails."""
    try:
        resp = await router.complete(
            role="classifier",
            messages=[{"role": "user", "content": user_text}],
            system=_CLASSIFIER_SYSTEM,
            tools=None,
        )
        result = resp.content.strip().upper()
        logger.info("classifier: %r → %s", user_text[:60], result)
        return result.startswith("QUICK")
    except Exception as exc:
        logger.warning("classifier LLM call failed (%s) — falling back to heuristic", exc)
        return _classify_quick_heuristic(user_text)


def _classify_quick_heuristic(text: str) -> bool:
    """Fallback heuristic classifier used when the LLM classifier is unavailable."""
    text_lower = text.strip().lower()
    if len(text_lower) < 15:
        return True
    quick_patterns = ("hi", "hello", "thanks", "ok", "yes", "no", "sure", "what time")
    return any(text_lower.startswith(p) for p in quick_patterns)
