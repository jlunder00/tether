"""Conversation utilities for Tether.

System prompt assembly and tool result formatting.
Advanced features (conversation_loop, LLM classifier, multi-turn sessions)
are available via tether-premium.
"""
import logging
from datetime import date

from bot.llm import LLMResponse, ToolCall

logger = logging.getLogger(__name__)


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
