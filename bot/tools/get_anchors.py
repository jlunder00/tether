"""Tool: get_anchors — list all anchor definitions."""
import json
import db.postgres as pg
from bot.tools.base import Tool, ToolResult
from db.pg_queries import get_anchors


async def _execute(inp: dict, ctx) -> ToolResult:
    try:
        async with pg.get_conn(ctx.pool, ctx.user_id) as conn:
            anchors = await get_anchors(conn)
        return ToolResult.ok(json.dumps(anchors, indent=2))
    except Exception as e:
        return ToolResult.error(f"Could not fetch anchors: {e}")


TOOL = Tool(
    name="get_anchors",
    description="List all time-block anchor definitions (id, name, time, duration).",
    input_schema={"type": "object", "properties": {}},
    execute=_execute,
    read_only=True,
)
