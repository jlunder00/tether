"""Tool: upsert_context_entry — full rewrite of a context entry."""
from bot.tools.base import Tool, ToolResult
from db.queries import upsert_context_entry


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    body = inp.get("body", "").strip()
    if not subject:
        return ToolResult.error("subject is required")
    try:
        upsert_context_entry(ctx.db_path, subject, body)
        return ToolResult.ok(f"Context entry {subject!r} updated.")
    except Exception as e:
        return ToolResult.error(f"Failed to upsert context entry: {e}")


TOOL = Tool(
    name="upsert_context_entry",
    description="Create or fully overwrite a context entry. Use append_context_entry to add without overwriting.",
    input_schema={
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Subject path, e.g. 'Work/Alpha'"},
            "body": {"type": "string", "description": "Full markdown body"},
        },
        "required": ["subject", "body"],
    },
    execute=_execute,
    read_only=False,
)
