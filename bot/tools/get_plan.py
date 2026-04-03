"""Tool: get_plan — fetch today's plan with task statuses."""
import json
from datetime import date
from bot.tools.base import Tool, ToolResult
from db.queries import get_plan


async def _execute(inp: dict, ctx) -> ToolResult:
    target_date = inp.get("date") or date.today().isoformat()
    try:
        plan = get_plan(ctx.db_path, target_date)
        return ToolResult.ok(json.dumps(plan, indent=2))
    except Exception as e:
        return ToolResult.error(f"Could not fetch plan: {e}")


TOOL = Tool(
    name="get_plan",
    description="Get the task plan for a given date (default today). Returns anchors with tasks and statuses.",
    input_schema={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "ISO date YYYY-MM-DD, defaults to today"},
        },
    },
    execute=_execute,
    read_only=True,
)
