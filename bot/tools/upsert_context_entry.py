"""Tool: upsert_context_entry — create/overwrite a context node's details section."""
from bot.tools.base import Tool, ToolResult
from db.queries import ensure_node_path, upsert_section


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    body = inp.get("body", "").strip()
    if not subject:
        return ToolResult.error("subject is required")
    try:
        node = ensure_node_path(ctx.db_path, subject)
        upsert_section(ctx.db_path, node["id"], "details", body)
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
