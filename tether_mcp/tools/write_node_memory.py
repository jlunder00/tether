"""write_node_memory MCP tool — write bot-authored notes to a context node section.

Writes to node_sections with origin='conversation_agent'. Supports three modes:
  additive — append content to existing body (or create if absent)
  edit     — replace existing body entirely
  delete   — remove the named section

Read-before-write enforcement (v2 HARD):
  conversation_id is required. A read of the target node must exist in
  node_read_log for the given conversation_id before any write is allowed
  (additive, edit, or delete). Returns a structured error if either condition
  is not met — no warning, no fallthrough.

All SQL lives in db/pg_queries/sections.py and db/pg_queries/node_memory.py.
"""
from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)


async def execute_write_node_memory(
    conn: asyncpg.Connection,
    node_id: str,
    title: str,
    data_type: str,
    value: str,
    mode: str = "additive",
    *,
    conversation_id: str | None = None,
    visible_to_user: bool = True,
    user_id: str | None = None,
) -> dict:
    """Write a bot-authored section to a context node.

    Args:
        conn:            asyncpg connection (user-scoped via RLS).
        node_id:         UUID of the context node to write to.
        title:           Section name (the 'name' column in node_sections).
        data_type:       Content type hint ('text' | 'list' | 'json' | 'file').
                         Used as the section_type; defaults to 'bot_notes'.
        value:           Content body to write.
        mode:            'additive' | 'edit' | 'delete'.
        conversation_id: Current conversation UUID. Required — writes are rejected
                         without it (v2 enforcement).
        visible_to_user: False hides this section from user-facing reads.

    Returns:
        On success: {status: 'ok', node_id, title, mode, section_type}
        On delete not found: {status: 'not_found', node_id, title}
        On bad mode: {error: 'invalid_mode', valid_modes: [...]}
        On missing conversation_id: {error: 'conversation_id_required', message: str}
        On missing prior read: {error: 'read_before_write_required', message: str}
    """
    from db.pg_queries.node_memory import has_read_node_in_conversation, log_node_read
    from db.pg_queries.sections import get_section, upsert_section, append_section, delete_section

    if mode not in ("additive", "edit", "delete"):
        return {
            "error": "invalid_mode",
            "valid_modes": ["additive", "edit", "delete"],
        }

    # v2: conversation_id is required for all writes
    if conversation_id is None:
        return {
            "error": "conversation_id_required",
            "message": "conversation_id is required for write_node_memory in v2.",
        }

    # v2: a read of this node must exist in node_read_log for this conversation
    has_read = await has_read_node_in_conversation(
        conn, node_id, conversation_id, user_id=user_id
    )
    if not has_read:
        return {
            "error": "read_before_write_required",
            "message": (
                "Must call read_node_memory for this node before writing "
                "in the same conversation."
            ),
        }

    section_type = data_type if data_type else "bot_notes"

    if mode == "delete":
        existing = await get_section(conn, node_id, section_type, name=title)
        if existing is None:
            return {"status": "not_found", "node_id": node_id, "title": title}
        await delete_section(conn, node_id, section_type, name=title)
        return {"status": "ok", "node_id": node_id, "title": title, "mode": "delete"}

    if mode == "additive":
        await append_section(
            conn, node_id, section_type, value, name=title,
            origin="conversation_agent", visible_to_user=visible_to_user,
        )
    else:  # edit
        await upsert_section(
            conn, node_id, section_type, value, name=title,
            origin="conversation_agent", visible_to_user=visible_to_user,
        )

    # Log write as a read credit so future reads know this conversation touched the node
    try:
        await log_node_read(
            conn, node_id, 999, conversation_id=conversation_id, title=title,
            user_id=user_id,
        )
    except Exception:
        pass  # don't fail the write if log fails

    return {
        "status": "ok",
        "node_id": node_id,
        "title": title,
        "mode": mode,
        "section_type": section_type,
    }
