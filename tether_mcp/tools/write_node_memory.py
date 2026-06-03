"""write_node_memory MCP tool — write bot-authored notes to a context node section.

Writes to node_sections with origin='conversation_agent'. Supports three modes:
  additive — append content to existing body (or create if absent)
  edit     — replace existing body entirely
  delete   — remove the named section

Read-before-write enforcement (v1 ADVISORY):
  On mode='edit' or mode='delete', checks node_read_log for any read of this
  node in the current conversation. If no read is logged, emits a warning in
  the response but allows the write.

  v2 (post-Stream-C-stable): flip to hard block by returning
  {error: 'read_before_write_violated', ...} instead of warning.

All writes set origin='conversation_agent' and visible_to_user=True by default
(the section is visible to the user in the UI). Pass visible_to_user=False for
internal bot notes that should be hidden from the user-facing context.
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
) -> dict:
    """Write a bot-authored section to a context node.

    Args:
        conn:            asyncpg connection (user-scoped via RLS).
        node_id:         UUID of the context node to write to.
        title:           Section name (the 'name' column in node_sections).
        data_type:       Hint for content type ('text' | 'list' | 'json' | 'file').
                         Stored as the section_type; 'notes' if not provided.
        value:           Content body to write.
        mode:            'additive' | 'edit' | 'delete'.
        conversation_id: Current conversation ID for read-before-write advisory.
        visible_to_user: False hides this section from user-facing reads.

    Returns:
        On success: {status: 'ok', node_id, title, mode, warning?: str}
        On delete (nothing to delete): {status: 'not_found', node_id, title}
        On error: {error: str, ...}
    """
    from db.pg_queries.node_memory import has_read_node_in_conversation, log_node_read
    from db.pg_queries.sections import (
        get_section,
        upsert_section,
        append_section,
        delete_section,
    )

    if mode not in ("additive", "edit", "delete"):
        return {
            "error": "invalid_mode",
            "valid_modes": ["additive", "edit", "delete"],
        }

    # Advisory read-before-write check for edit / delete
    warning: str | None = None
    if mode in ("edit", "delete") and conversation_id is not None:
        has_read = await has_read_node_in_conversation(conn, node_id, conversation_id)
        if not has_read:
            warning = (
                f"read_before_write_advisory: no read of node {node_id} logged "
                f"in conversation {conversation_id} — writing anyway (v1 advisory mode)"
            )
            logger.warning(warning)
    elif mode in ("edit", "delete") and conversation_id is None:
        warning = "read_before_write_advisory: conversation_id not provided — skipping read check"
        logger.warning(warning)

    # Derive section_type from data_type or default to 'bot_notes'
    section_type = data_type if data_type else "bot_notes"

    if mode == "delete":
        existing = await get_section(conn, node_id, section_type, name=title)
        if existing is None:
            return {"status": "not_found", "node_id": node_id, "title": title}
        await delete_section(conn, node_id, section_type, name=title)
        result = {"status": "ok", "node_id": node_id, "title": title, "mode": "delete"}
        if warning:
            result["warning"] = warning
        return result

    # Build the section body with origin marker.
    # upsert_section / append_section don't yet accept origin/visible_to_user —
    # we write directly so we can set the new columns properly.
    import uuid as _uuid

    node_uuid = _uuid.UUID(node_id)
    user_uuid = await conn.fetchval(
        "SELECT current_setting('app.current_user_id', true)::uuid"
    )

    if mode == "additive":
        existing = await get_section(conn, node_id, section_type, name=title)
        if existing and existing["body"]:
            new_body = existing["body"] + "\n\n" + value
        else:
            new_body = value
    else:  # edit
        new_body = value

    # Use INSERT ... ON CONFLICT so we can set origin + visible_to_user.
    next_pos = await conn.fetchval(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM node_sections "
        "WHERE node_id = $1 AND section_type = $2",
        node_uuid, section_type,
    )
    await conn.execute(
        """
        INSERT INTO node_sections
            (user_id, node_id, section_type, name, body, position,
             origin, visible_to_user, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, 'conversation_agent', $7, now())
        ON CONFLICT (node_id, section_type, name) DO UPDATE
            SET body           = EXCLUDED.body,
                origin         = 'conversation_agent',
                visible_to_user = EXCLUDED.visible_to_user,
                updated_at     = now(),
                version        = node_sections.version + 1
        """,
        user_uuid, node_uuid, section_type, title, new_body, next_pos, visible_to_user,
    )
    await conn.execute(
        "UPDATE context_nodes SET updated_at = now() WHERE id = $1", node_uuid
    )

    # Log the write read-credit (so future writes know this conversation touched the node)
    if conversation_id is not None:
        try:
            await log_node_read(
                conn, node_id, 999, conversation_id=conversation_id, title=title
            )
        except Exception:
            pass  # don't fail the write if log fails

    result = {
        "status": "ok",
        "node_id": node_id,
        "title": title,
        "mode": mode,
        "section_type": section_type,
    }
    if warning:
        result["warning"] = warning
    return result
