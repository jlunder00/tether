"""Tool: get_context_entry — fetch context node details by path."""
import db.postgres as pg
from bot.tools.base import Tool, ToolResult
from db.pg_queries import get_node_by_path, get_section


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    if not subject:
        return ToolResult.error("subject is required")
    try:
        async with pg.get_conn(ctx.pool, ctx.user_id) as conn:
            node = await get_node_by_path(conn, subject)
            if not node:
                return ToolResult.error(f"No context node found for path: {subject!r}")
            sec = await get_section(conn, node["id"], "details")
        body = sec["body"] if sec else "(no details section)"
        return ToolResult.ok(body)
    except Exception as e:
        return ToolResult.error(f"Could not fetch context: {e}")


TOOL = Tool(
    name="get_context_entry",
    description="Fetch the details section of a context node by its path (e.g. 'Work/Alpha').",
    input_schema={
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Node path, e.g. 'Work/Alpha'"},
        },
        "required": ["subject"],
    },
    execute=_execute,
    read_only=True,
)
