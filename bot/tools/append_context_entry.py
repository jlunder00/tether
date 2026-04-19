"""Tool: append_context_entry — append content to a context node's details section."""
import db.postgres as pg
from bot.tools.base import Tool, ToolResult
from db.pg_queries import ensure_node_path, append_section


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    content = inp.get("content", "")
    if not subject:
        return ToolResult.error("subject is required")
    try:
        async with pg.get_conn(ctx.pool, ctx.user_id) as conn:
            node = await ensure_node_path(conn, subject)
            await append_section(conn, node["id"], "details", content)
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
