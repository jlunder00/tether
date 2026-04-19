"""Tool: upsert_context_entry — create/overwrite a context node's details section."""
import db.postgres as pg
from bot.tools.base import Tool, ToolResult
from db.pg_queries import ensure_node_path, upsert_section


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    body = inp.get("body", "").strip()
    if not subject:
        return ToolResult.error("subject is required")
    try:
        async with pg.get_conn(ctx.pool, ctx.user_id) as conn:
            node = await ensure_node_path(conn, subject)
            await upsert_section(conn, node["id"], "details", body)
        return ToolResult.ok(f"Context node {subject!r} updated.")
    except Exception as e:
        return ToolResult.error(f"Failed to upsert context: {e}")


TOOL = Tool(
    name="upsert_context_entry",
    description="Create or fully overwrite a context node's details. Use append_context_entry to add without overwriting.",
    input_schema={
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Node path, e.g. 'Work/Alpha'"},
            "body": {"type": "string", "description": "Full markdown body"},
        },
        "required": ["subject", "body"],
    },
    execute=_execute,
    read_only=False,
)
