"""Tool: search_context — list context node paths."""
from bot.tools.base import Tool, ToolResult
from db.queries import get_all_node_paths


async def _execute(inp: dict, ctx) -> ToolResult:
    try:
        paths = get_all_node_paths(ctx.db_path)
        prefix = inp.get("prefix", "")
        if prefix:
            paths = [p for p in paths if p.startswith(prefix)]
        if not paths:
            return ToolResult.ok("No context nodes found.")
        return ToolResult.ok("\n".join(paths))
    except Exception as e:
        return ToolResult.error(f"Could not list context nodes: {e}")


TOOL = Tool(
    name="search_context",
    description="List context node paths, optionally filtered by path prefix.",
    input_schema={
        "type": "object",
        "properties": {
            "prefix": {"type": "string", "description": "Path prefix to filter by, e.g. 'Work'"},
        },
    },
    execute=_execute,
    read_only=True,
)
