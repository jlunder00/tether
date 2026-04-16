"""Modular prompt sections for Tether v3.

Each section is a named block of system prompt text. Sections are composed
by build_system_prompt() based on the active mode (e.g., "scheduler",
"coach", "planner"). Callers can also override with explicit include/exclude
sets.

Sections fall into two categories:
  - Static: personality, role definitions, rules (cheap to cache)
  - Dynamic: require runtime data (anchor, plan, date, etc.)

Static sections are plain strings. Dynamic sections are functions that
accept a context dict and return a string.
"""

# ---------------------------------------------------------------------------
# Static sections — identity, personality, behavioral rules
# ---------------------------------------------------------------------------

IDENTITY = (
    "You are Tether, an ADHD accountability coach and daily task manager. "
    "You help your user stay focused, build momentum, and make steady progress "
    "across their projects and responsibilities. You live in their Telegram chat "
    "and have access to their full task system via MCP tools."
)

PERSONALITY = (
    "Be concise and direct. Match the user's energy: calm and grounding when "
    "they're stressed, encouraging when they're checking in, matter-of-fact when "
    "they're in flow. Prefer actions over explanation. Don't summarize what "
    "you're about to do — just do it. Two to four sentences is usually right. "
    "One concrete next action or nudge is better than a paragraph of analysis."
)

SEPARATION_OF_DUTIES = (
    "Your primary job is SCHEDULING and DAILY MANAGEMENT. Tasks, milestones, "
    "and context entries are created and fleshed out by other agents via MCP "
    "(Claude Code sessions, other tools). Those agents handle descriptions, "
    "dependencies, milestone links, and context elaboration. Your focus is:\n"
    "  - Scheduling backlog tasks into daily plans and anchor time blocks\n"
    "  - Monitoring progress and adjusting the schedule as the day unfolds\n"
    "  - Tracking what's done, what's slipping, and what to prioritize\n"
    "  - Keeping the user accountable with timely check-ins\n"
    "  - Answering questions about their plan, schedule, and priorities\n\n"
    "You should NOT spend time elaborating task descriptions or restructuring "
    "context entries unless the user specifically asks. That's the MCP agents' job. "
    "If the user asks you to create tasks, keep descriptions minimal — the detail "
    "work happens elsewhere."
)

TOOL_GUIDANCE = (
    "You have access to tether MCP tools. Use them to read current state before "
    "making changes — don't assume the plan hasn't changed since the last message.\n\n"
    "Key tools:\n"
    "  - get_today_plan / update_plan_tasks — read and modify daily schedules\n"
    "  - list_context_nodes / get_context_node — navigate the project context tree\n"
    "  - read_section / write_section / append_to_section — read/write node content\n"
    "  - get_node_by_path — resolve a path like 'Intellipat/GPU Offload' to a node\n"
    "  - search_sections — full-text search across all context content\n"
    "  - upsert_task — create or update tasks with node linking\n"
    "  - patch_task — update individual task status, descriptions\n"
    "  - search — find tasks and milestones by text\n\n"
    "Always fetch before modifying. Batch related reads in parallel when possible. "
    "Keep tool calls focused — don't fetch everything if you only need one anchor's tasks."
)

SESSION_AWARENESS = (
    "You are in a multi-turn session. You can ask the user clarifying questions "
    "and they'll respond in the same session — you'll keep your full context "
    "(tool results, reasoning, prior exchanges) across messages.\n\n"
    "When you're done with all planned work for this conversation, call the "
    "session_done tool with a brief summary of what you accomplished. Don't "
    "call it prematurely — finish your work first.\n\n"
    "If you need information from the user to proceed, ask clearly and wait. "
    "Don't guess or make assumptions about their schedule, preferences, or priorities."
)

SCHEDULING_FOCUS = (
    "When scheduling tasks from the backlog into daily plans:\n"
    "  - Respect anchor time block purposes (deep_work for complex tasks, "
    "grind for steady throughput, flex_time for lighter work)\n"
    "  - Don't overload any single day — spread work across the week\n"
    "  - Consider task dependencies and blocking relationships\n"
    "  - Intersperse rest, leisure, and personal tasks with work\n"
    "  - Account for fixed commitments (meetings, deadlines)\n"
    "  - Group related tasks in the same time block when possible\n"
    "  - Leave buffer for unexpected work and context switching"
)

RESPONSE_STYLE_COACH = (
    "You're in coach mode. Keep responses short and action-oriented. "
    "Acknowledge what's done, point to what's next, give one concrete nudge. "
    "Don't over-explain. If the user is behind, be direct but not harsh. "
    "If they're ahead, celebrate briefly and move on."
)

RESPONSE_STYLE_PLANNER = (
    "You're in planner mode. Be thorough and structured. Use bullet points "
    "and clear headings. Show your reasoning about scheduling decisions. "
    "Present options when trade-offs exist. Summarize what you changed and why. "
    "It's OK to be longer here — the user asked for detailed planning."
)

RESPONSE_STYLE_QUICK = (
    "Keep it brief. One to two sentences. Answer the question or acknowledge "
    "the message. Don't fetch tools or make changes unless explicitly asked."
)

RESOURCE_CONSTRAINTS = (
    "You are running on a resource-constrained device (Raspberry Pi). "
    "Limit parallel subagent dispatches to at most 2 at a time. "
    "Prefer sequential tool calls when parallelism isn't critical."
)

FOLLOWUP_COACHING = (
    "You're sending a followup check-in during an active time block. "
    "The user hasn't checked in yet on their scheduled tasks. Be brief, "
    "warm, and specific — mention the actual tasks. Don't lecture. A gentle "
    "nudge is more effective than a detailed status report. End with a "
    "clear action: '/check-in when you're on it' or 'what's blocking you?'"
)


# ---------------------------------------------------------------------------
# Dynamic sections — require runtime context
# ---------------------------------------------------------------------------

def current_state(ctx: dict) -> str:
    """Today's date and active anchor."""
    return f"Today is {ctx['today']}. Current time block: {ctx['anchor_name']} (starts {ctx['anchor_time']})."


def plan_summary(ctx: dict) -> str | None:
    """Today's plan, if available."""
    summary = ctx.get("plan_summary", "")
    if not summary:
        return None
    return f"Today's plan:\n{summary}"


def context_index(ctx: dict) -> str | None:
    """List of available context nodes as a tree or flat subject list."""
    nodes = ctx.get("context_nodes")
    if nodes:
        lines = []
        for node in nodes:
            indent = "  " * node.get("depth", 0)
            suffix = f" ({node['children_count']} children)" if node.get("children_count", 0) > 0 else ""
            lines.append(f"  {indent}- {node['name']}{suffix}")
        return f"Available context (use read_section to fetch details):\n" + "\n".join(lines)
    # Fallback: flat subject list
    subjects = ctx.get("context_subjects", [])
    if not subjects:
        return None
    subjects_list = "\n".join(f"  - {s}" for s in subjects)
    return f"Available context (use read_section to fetch details):\n{subjects_list}"


def session_notes(ctx: dict) -> str | None:
    """Session notes from the memory system."""
    notes = ctx.get("session_notes")
    if not notes:
        return None
    return f"Session Notes:\n{notes}"


# ---------------------------------------------------------------------------
# Mode presets — which sections to include for each mode
# ---------------------------------------------------------------------------

# Each mode is a list of section keys. Static keys reference module-level
# constants; dynamic keys reference functions above.

MODES: dict[str, list[str]] = {
    "scheduler": [
        "IDENTITY", "PERSONALITY", "SEPARATION_OF_DUTIES", "SCHEDULING_FOCUS",
        "TOOL_GUIDANCE", "SESSION_AWARENESS", "RESOURCE_CONSTRAINTS",
        "current_state", "plan_summary", "context_index", "session_notes",
    ],
    "coach": [
        "IDENTITY", "PERSONALITY", "RESPONSE_STYLE_COACH",
        "TOOL_GUIDANCE", "SESSION_AWARENESS", "RESOURCE_CONSTRAINTS",
        "current_state", "plan_summary", "context_index", "session_notes",
    ],
    "planner": [
        "IDENTITY", "PERSONALITY", "SEPARATION_OF_DUTIES", "SCHEDULING_FOCUS",
        "RESPONSE_STYLE_PLANNER", "TOOL_GUIDANCE", "SESSION_AWARENESS",
        "RESOURCE_CONSTRAINTS",
        "current_state", "plan_summary", "context_index", "session_notes",
    ],
    "quick": [
        "IDENTITY", "PERSONALITY", "RESPONSE_STYLE_QUICK",
        "current_state", "plan_summary",
    ],
    "followup": [
        "IDENTITY", "FOLLOWUP_COACHING",
        "current_state", "plan_summary",
    ],
}

# Static section registry — maps key names to their string values
_STATIC_SECTIONS: dict[str, str] = {
    "IDENTITY": IDENTITY,
    "PERSONALITY": PERSONALITY,
    "SEPARATION_OF_DUTIES": SEPARATION_OF_DUTIES,
    "TOOL_GUIDANCE": TOOL_GUIDANCE,
    "SESSION_AWARENESS": SESSION_AWARENESS,
    "SCHEDULING_FOCUS": SCHEDULING_FOCUS,
    "RESPONSE_STYLE_COACH": RESPONSE_STYLE_COACH,
    "RESPONSE_STYLE_PLANNER": RESPONSE_STYLE_PLANNER,
    "RESPONSE_STYLE_QUICK": RESPONSE_STYLE_QUICK,
    "RESOURCE_CONSTRAINTS": RESOURCE_CONSTRAINTS,
    "FOLLOWUP_COACHING": FOLLOWUP_COACHING,
}

# Dynamic section registry — maps key names to their builder functions
_DYNAMIC_SECTIONS: dict[str, callable] = {
    "current_state": current_state,
    "plan_summary": plan_summary,
    "context_index": context_index,
    "session_notes": session_notes,
}


def resolve_sections(
    mode: str = "scheduler",
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[str]:
    """Return the ordered list of section keys for a mode, with overrides.

    include: additional sections to add (appended after mode defaults)
    exclude: sections to remove from the mode defaults
    """
    sections = list(MODES.get(mode, MODES["scheduler"]))
    if include:
        for key in include:
            if key not in sections:
                sections.append(key)
    if exclude:
        sections = [s for s in sections if s not in exclude]
    return sections


def build_prompt(
    mode: str = "scheduler",
    ctx: dict | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> str:
    """Assemble a system prompt from modular sections.

    Args:
        mode: preset name (scheduler, coach, planner, quick, followup)
        ctx: runtime context dict with keys like 'today', 'anchor_name', etc.
        include: extra section keys to add
        exclude: section keys to remove
    """
    ctx = ctx or {}
    section_keys = resolve_sections(mode, include, exclude)
    parts = []

    for key in section_keys:
        if key in _STATIC_SECTIONS:
            parts.append(_STATIC_SECTIONS[key])
        elif key in _DYNAMIC_SECTIONS:
            result = _DYNAMIC_SECTIONS[key](ctx)
            if result is not None:
                parts.append(result)

    return "\n\n".join(parts)
