"""Context injection helper — Phase G.

Builds a formatted markdown context block from a conversation's linked
context node for injection into bot pipeline prompts.

Public interface:
    build_conversation_context(conversation_id, pool, user_id) -> str

Returns an empty string when no context_node_id is set, or when the linked
node no longer exists (e.g. after deletion).
"""
from __future__ import annotations

import logging

from db.pg_queries.conversations import get_conversation
from db.pg_queries.nodes import get_node
from db.pg_queries.sections import get_sections

_log = logging.getLogger(__name__)


async def build_conversation_context(
    conversation_id: str,
    pool,
    user_id: str,
) -> str:
    """Return a formatted markdown context block for the given conversation.

    Fetches:
      - The conversation's linked context_node (if any)
      - All sections attached to that node

    Returns an empty string when there is no context to inject, so callers
    can safely do: ``if ctx := await build_conversation_context(...): ...``
    """
    async with pool.acquire() as conn:
        # Set RLS so node/section queries are user-scoped.
        await conn.execute(
            "SELECT set_config('app.current_user_id', $1, true)", user_id
        )

        conv = await get_conversation(conn, conversation_id)
        if not conv or not conv.get("context_node_id"):
            return ""

        node_id = conv["context_node_id"]
        node = await get_node(conn, node_id)
        if node is None:
            _log.debug("build_conversation_context: node %s not found", node_id)
            return ""

        sections = await get_sections(conn, node_id)

    # Cross-node parent summary is handled in tether-premium (not in OSS).
    return _format_context_block(node, sections)


def _format_context_block(node: dict, sections: list[dict]) -> str:
    """Render a markdown block summarising the context node and its sections."""
    lines = [f"## Context: {node['name']}", ""]

    if not sections:
        # Node exists but has no sections — still useful to name it
        lines.append("*(no section content)*")
    else:
        for sec in sections:
            label = sec["section_type"].replace("_", " ").title()
            lines += [f"### {label}", sec["body"] or "", ""]

    return "\n".join(lines).rstrip() + "\n"
