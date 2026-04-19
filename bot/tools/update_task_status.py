"""Tool: update_task_status — set the status of an existing task by ID."""
import db.postgres as pg
from bot.tools.base import Tool, ToolResult
from db.pg_queries import patch_task_fields

VALID_STATUSES = {"pending", "in_progress", "done", "skipped", "blocked"}


async def _execute(inp: dict, ctx) -> ToolResult:
    task_id = inp.get("task_id", "").strip()
    status = inp.get("status", "").strip()
    if not task_id:
        return ToolResult.error("task_id is required")
    if status not in VALID_STATUSES:
        return ToolResult.error(f"Invalid status {status!r}. Must be one of: {sorted(VALID_STATUSES)}")
    try:
        async with pg.get_conn(ctx.pool, ctx.user_id) as conn:
            result = await patch_task_fields(conn, task_id, {"status": status})
        if result is None:
            return ToolResult.error(f"Task not found: {task_id!r}")
        return ToolResult.ok(f"Task {task_id} status set to {status!r}")
    except Exception as e:
        return ToolResult.error(f"Failed to update task status: {e}")


TOOL = Tool(
    name="update_task_status",
    description="Set the status of an existing task by its UUID.",
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "UUID of the task"},
            "status": {"type": "string", "enum": sorted(VALID_STATUSES)},
        },
        "required": ["task_id", "status"],
    },
    execute=_execute,
    read_only=False,
)
