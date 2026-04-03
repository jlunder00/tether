"""Tool: patch_context_entry — targeted find-and-replace in a context entry."""
from bot.tools.base import Tool, ToolResult
from db.queries import get_context_entries, upsert_context_entry


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    old_string = inp.get("old_string", "")
    new_string = inp.get("new_string", "")
    if not subject or not old_string:
        return ToolResult.error("subject and old_string are required")
    try:
        entries = get_context_entries(ctx.db_path, prefix=subject)
        exact = [e for e in entries if e["subject"] == subject]
        if not exact:
            return ToolResult.error(f"No context entry found for subject: {subject!r}")
        body = exact[0]["body"]
        if old_string not in body:
            return ToolResult.error(
                f"old_string not found in {subject!r}. No changes made."
            )
        new_body = body.replace(old_string, new_string, 1)
        upsert_context_entry(ctx.db_path, subject, new_body)
        return ToolResult.ok(f"Patched context entry {subject!r}.")
    except Exception as e:
        return ToolResult.error(f"Failed to patch context entry: {e}")


TOOL = Tool(
    name="patch_context_entry",
    description="Find and replace an exact string in a context entry. Fails if old_string is not found.",
    input_schema={
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to find"},
            "new_string": {"type": "string", "description": "Replacement text"},
        },
        "required": ["subject", "old_string", "new_string"],
    },
    execute=_execute,
    read_only=False,
    guardrails=["patch_exact_match"],
)
