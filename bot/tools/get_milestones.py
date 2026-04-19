"""Tool: get_milestones — list milestones with task completion status."""
import json
import db.postgres as pg
from bot.tools.base import Tool, ToolResult
from db.pg_queries import get_milestones


async def _execute(inp: dict, ctx) -> ToolResult:
    context_subject = inp.get("context_subject") or None
    try:
        async with pg.get_conn(ctx.pool, ctx.user_id) as conn:
            milestones = await get_milestones(conn, context_subject=context_subject)
        if not milestones:
            return ToolResult.ok("No milestones found.")
        # Compact representation — full task list is expensive, just show summary
        summaries = []
        for m in milestones:
            pct = int(m["done_count"] / m["task_count"] * 100) if m["task_count"] else 0
            summaries.append({
                "id": m["id"],
                "name": m["name"],
                "context_subject": m["context_subject"],
                "status": m["status"],
                "progress": f"{m['done_count']}/{m['task_count']} ({pct}%)",
                "target_date": m["target_date"],
            })
        return ToolResult.ok(json.dumps(summaries, indent=2))
    except Exception as e:
        return ToolResult.error(f"Could not fetch milestones: {e}")


TOOL = Tool(
    name="get_milestones",
    description="List milestones with completion progress, optionally filtered by context subject.",
    input_schema={
        "type": "object",
        "properties": {
            "context_subject": {
                "type": "string",
                "description": "Filter by context subject, e.g. 'Work/Alpha'. Omit for all milestones.",
            },
        },
    },
    execute=_execute,
    read_only=True,
)
