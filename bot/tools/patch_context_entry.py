"""Tool: patch_context_entry — targeted find-and-replace in a context node's details."""
import db.postgres as pg
from bot.tools.base import Tool, ToolResult
from db.pg_queries import get_node_by_path, get_section, upsert_section


async def _execute(inp: dict, ctx) -> ToolResult:
    subject = inp.get("subject", "").strip()
    old_string = inp.get("old_string", "")
    new_string = inp.get("new_string", "")
    if not subject or not old_string:
        return ToolResult.error("subject and old_string are required")
    try:
        async with pg.get_conn(ctx.pool, ctx.user_id) as conn:
            node = await get_node_by_path(conn, subject)
            if not node:
                return ToolResult.error(f"No context node found for path: {subject!r}")
            sec = await get_section(conn, node["id"], "details")
            if not sec:
                return ToolResult.error(f"No details section found for {subject!r}")
            body = sec["body"]
            if old_string not in body:
                return ToolResult.error(
                    f"old_string not found in {subject!r}. No changes made."
                )
            new_body = body.replace(old_string, new_string, 1)
            await upsert_section(conn, node["id"], "details", new_body)
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
