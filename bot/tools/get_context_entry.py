"""Tool: get_context_entry — fetch the body of a context entry by subject."""
from bot.tools.base import Tool, ToolResult
from db.queries import get_context_entries


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    if not subject:
        return ToolResult.error("subject is required")
    try:
        entries = get_context_entries(ctx.db_path, prefix=subject)
        exact = [e for e in entries if e["subject"] == subject]
        if not exact:
            return ToolResult.error(f"No context entry found for subject: {subject!r}")
        return ToolResult.ok(exact[0]["body"])
    except Exception as e:
        return ToolResult.error(f"Could not fetch context entry: {e}")


TOOL = Tool(
    name="get_context_entry",
    description="Fetch the full body of a context entry by its exact subject path.",
    input_schema={
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Exact subject path, e.g. 'Work/Alpha'"},
        },
        "required": ["subject"],
    },
    execute=_execute,
    read_only=True,
)
