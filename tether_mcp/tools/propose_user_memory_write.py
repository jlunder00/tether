"""propose_user_memory_write MCP tool — stage a user_memory proposal for Beacon review.

The interactive 2.5 agent calls this tool when the user says something like
"remember that I prefer mornings." The proposal is NOT committed immediately:

  1. Tool inserts a row in pending_memory_writes with status='pending'.
  2. Tool returns proposal_id to the agent (can be echoed to the user).
  3. Beacon's post-conversation evaluator reads pending_memory_writes after
     the conversation concludes (~40min idle) and decides to accept or reject:
       - User-invoked proposals: auto-accept.
       - Agent-inferred without user request: review with caution.
  4. Accepted proposals: Beacon writes to user_memory via upsert_user_memory().
  5. Rejected proposals: status set to 'rejected'; no write to user_memory.

This design keeps the interactive agent out of the direct-write path while
surfacing the intent to the user and Beacon.
"""
from __future__ import annotations

import asyncpg


async def execute_propose_user_memory_write(
    conn: asyncpg.Connection,
    key: str,
    value: str,
    reason: str,
    *,
    conversation_id: str | None = None,
) -> dict:
    """Stage a user_memory write proposal for Beacon review.

    Args:
        conn:            asyncpg connection (user-scoped via RLS).
        key:             Memory key (e.g., 'preferences/morning_routine').
        value:           Value to write (e.g., 'prefers structured plan by 8am').
        reason:          Why this write is proposed (context for Beacon evaluator).
        conversation_id: Current conversation UUID (linked to the proposal).

    Returns:
        {status: 'proposed', proposal_id: str, key: str, message: str}
        On error: {error: str}
    """
    from db.pg_queries.memory import insert_pending_memory_write

    if not key or not key.strip():
        return {"error": "key_required", "message": "key must be a non-empty string"}
    if not value:
        return {"error": "value_required", "message": "value must be non-empty"}
    if not reason or not reason.strip():
        return {"error": "reason_required", "message": "reason is required for Beacon review"}

    proposal_id = await insert_pending_memory_write(
        conn,
        key.strip(),
        value,
        reason.strip(),
        conversation_id=conversation_id,
    )

    return {
        "status": "proposed",
        "proposal_id": proposal_id,
        "key": key.strip(),
        "message": (
            "Memory write staged for Beacon review. It will be committed after "
            "this conversation concludes and Beacon evaluates it."
        ),
    }
