"""Tool: append_context_entry — append content to a context node's details section."""
from bot.tools.base import Tool, ToolResult
from db.queries import ensure_node_path, append_section


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    content = inp.get("content", "")
    if not subject:
        return ToolResult.error("subject is required")
    try:
        node = ensure_node_path(ctx.db_path, subject)
        append_section(ctx.db_path, node["id"], "details", content)
        return ToolResult.ok(f"Appended to context node {subject!r}.")
    except Exception as e:
        return ToolResult.error(f"Failed to append to context: {e}")


TOOL = Tool(
    name="append_context_entry",
    description="Append content to a context node's details. Creates the node if it doesn't exist.",
    input_schema={
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "content": {"type": "string", "description": "Text to append"},
        },
        "required": ["subject", "content"],
    },
    execute=_execute,
    read_only=False,
)
