"""read_node_memory MCP tool — read bot-authored notes on a specific context node.

Returns node_sections entries where origin='conversation_agent', optionally
filtered by title. This is the symmetric read side of write_node_memory.

Also logs the read to node_read_log (enabling the read-before-write advisory
for subsequent write_node_memory calls in the same conversation).

Alternatively, read_context with source='memory' or source='both' covers this
case for multi-node reads. read_node_memory is the focused single-node version.
"""
from __future__ import annotations

import asyncpg


async def execute_read_node_memory(
    conn: asyncpg.Connection,
    node_id: str,
    title: str | None = None,
    M: int = 4,
    *,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Return bot-authored sections for a context node.

    Args:
        conn:            asyncpg connection (user-scoped via RLS).
        node_id:         UUID of the context node.
        title:           Optional section name filter.
        M:               Detail level — 1 (names only), 2 (preview), 3 (truncated), 4 (full).
        conversation_id: Current conversation UUID (for read-credit logging).
        user_id:         RLS hardening — explicit caller-supplied user_id, bound
                         directly on the read-credit insert. Optional, backward
                         compatible.

    Returns:
        {node_id, sections: [{section_type, name, body?, preview?, origin}]}
        Or {error: 'node_not_found'} if node doesn't exist.
    """
    from db.pg_queries import get_node
    from db.pg_queries.node_memory import log_node_read
    from db.pg_queries.sections import get_sections

    # Verify node exists
    node = await get_node(conn, node_id)
    if node is None:
        return {"error": "node_not_found", "node_id": node_id}

    all_sections = await get_sections(conn, node_id)

    # Filter to bot-authored only
    bot_sections = [
        s for s in all_sections
        if s.get("origin") == "conversation_agent"
    ]

    # Optional title filter
    if title is not None:
        bot_sections = [s for s in bot_sections if s.get("name") == title]

    # Apply M-level to body content
    def format_body(body: str | None) -> str | None:
        if not body:
            return body
        if M == 1:
            return None  # name only
        if M == 2:
            return body[:50] if len(body) > 50 else body
        if M == 3:
            return body[:200] if len(body) > 200 else body
        return body  # M=4: full

    sections_out = []
    for s in bot_sections:
        entry: dict = {
            "section_type": s["section_type"],
            "name": s["name"],
            "origin": s.get("origin", "conversation_agent"),
            "visible_to_user": s.get("visible_to_user", True),
        }
        if M > 1:
            entry["body"] = format_body(s.get("body"))
        sections_out.append(entry)

    # Log read credit
    if conversation_id:
        try:
            await log_node_read(
                conn, node_id, M,
                conversation_id=conversation_id,
                title=node.get("name"),
                user_id=user_id,
            )
        except Exception:
            pass

    return {
        "node_id": node_id,
        "node_name": node.get("name"),
        "M": M,
        "sections": sections_out,
        "total": len(sections_out),
    }
