"""Tool: upsert_task — create or update a task in an anchor."""
from datetime import date
from bot.tools.base import Tool, ToolResult
from db.queries import upsert_tasks, get_anchors


async def _execute(inp: dict, ctx) -> ToolResult:
    anchor_id = inp.get("anchor_id", "").strip()
    text = inp.get("text", "").strip()
    if not anchor_id or not text:
        return ToolResult.error("anchor_id and text are required")

    # Validate anchor exists
    try:
        anchors = get_anchors(ctx.db_path)
        anchor_ids = {a["id"] for a in anchors}
        if anchor_id not in anchor_ids:
            return ToolResult.error(f"Unknown anchor_id: {anchor_id!r}")
    except Exception as e:
        return ToolResult.error(f"Could not validate anchor: {e}")

    target_date = inp.get("date") or date.today().isoformat()
    task = {
        "text": text,
        "status": inp.get("status", "pending"),
        "position": inp.get("position"),
    }
    if inp.get("task_id"):
        task["id"] = inp["task_id"]

    try:
        upsert_tasks(ctx.db_path, target_date, anchor_id, [task])
        return ToolResult.ok(f"Task upserted in {anchor_id}: {text!r}")
    except Exception as e:
        return ToolResult.error(f"Failed to upsert task: {e}")


TOOL = Tool(
    name="upsert_task",
    description="Create or update a task in an anchor. Provide task_id to update an existing task.",
    input_schema={
        "type": "object",
        "properties": {
            "anchor_id": {"type": "string"},
            "text": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "done", "skipped", "blocked"]},
            "position": {"type": "integer"},
            "task_id": {"type": "string", "description": "UUID of existing task to update"},
            "date": {"type": "string", "description": "ISO date, defaults to today"},
        },
        "required": ["anchor_id", "text"],
    },
    execute=_execute,
    read_only=False,
)
