"""Tool: append_context_entry — add content to an existing context entry."""
from bot.tools.base import Tool, ToolResult
from db.queries import get_context_entries, upsert_context_entry


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    content = inp.get("content", "")
    if not subject:
        return ToolResult.error("subject is required")
    try:
        entries = get_context_entries(ctx.db_path, prefix=subject)
        exact = [e for e in entries if e["subject"] == subject]
        existing_body = exact[0]["body"] if exact else ""
        new_body = existing_body + content
        upsert_context_entry(ctx.db_path, subject, new_body)
        return ToolResult.ok(f"Appended to context entry {subject!r}.")
    except Exception as e:
        return ToolResult.error(f"Failed to append context entry: {e}")


TOOL = Tool(
    name="append_context_entry",
    description="Append content to an existing context entry. Creates it if it doesn't exist.",
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
