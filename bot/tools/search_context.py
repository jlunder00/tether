"""Tool: search_context — list context entry subjects matching a prefix."""
from bot.tools.base import Tool, ToolResult
from db.queries import get_context_entries


async def _execute(inp: dict, ctx) -> ToolResult:
    prefix = inp.get("prefix", "")
    try:
        entries = get_context_entries(ctx.db_path, prefix=prefix if prefix else None)
        subjects = [e["subject"] for e in entries]
        if not subjects:
            return ToolResult.ok("No context entries found.")
        return ToolResult.ok("\n".join(subjects))
    except Exception as e:
        return ToolResult.error(f"Could not search context: {e}")


TOOL = Tool(
    name="search_context",
    description="List context entry subject paths, optionally filtered by prefix.",
    input_schema={
        "type": "object",
        "properties": {
            "prefix": {"type": "string", "description": "Subject prefix to filter by, e.g. 'Work'"},
        },
    },
    execute=_execute,
    read_only=True,
)
