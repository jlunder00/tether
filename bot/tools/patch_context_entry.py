"""Tool: patch_context_entry — targeted find-and-replace in a context node's details."""
from bot.tools.base import Tool, ToolResult
from db.queries import get_node_by_path, get_section, upsert_section


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    old_string = inp.get("old_string", "")
    new_string = inp.get("new_string", "")
    if not subject or not old_string:
        return ToolResult.error("subject and old_string are required")
    try:
        node = get_node_by_path(ctx.db_path, subject)
        if not node:
            return ToolResult.error(f"No context node found for path: {subject!r}")
        sec = get_section(ctx.db_path, node["id"], "details")
        if not sec:
            return ToolResult.error(f"No details section found for {subject!r}")
        body = sec["body"]
        if old_string not in body:
            return ToolResult.error(
                f"old_string not found in {subject!r}. No changes made."
            )
        new_body = body.replace(old_string, new_string, 1)
        upsert_section(ctx.db_path, node["id"], "details", new_body)
        return ToolResult.ok(f"Patched context node {subject!r}.")
    except Exception as e:
        return ToolResult.error(f"Failed to patch context: {e}")


TOOL = Tool(
    name="patch_context_entry",
    description="Find and replace an exact string in a context node's details. Fails if old_string is not found.",
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
