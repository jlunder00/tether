"""Bot action audit log queries — log, count, and budget enforcement.

All functions take conn: asyncpg.Connection as first arg and operate
under the caller's RLS context (user_id must be set via set_config).

Budget defaults:
  coordination  — strict: task_created=1, task_updated=0, task_deleted=0
  general       — high:   task_created=10, task_updated=20, task_deleted=5

Budget is checked against persisted bot_actions rows so restarts and retries
are safe (no in-memory state required).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncpg


# ─── Budget configuration ─────────────────────────────────────────────────────

_BUDGETS: dict[str, dict[str, int]] = {
    "coordination": {
        "task_created": 1,
        "task_updated": 0,
        "task_deleted": 0,
    },
    "general": {
        "task_created": 10,
        "task_updated": 20,
        "task_deleted": 5,
    },
}

_DEFAULT_GENERAL_LIMIT = 20


def _budget_limit(action_type: str, session_type: str) -> int:
    """Return the budget limit for (action_type, session_type).

    Falls back to the general default for unknown action types.
    """
    budget = _BUDGETS.get(session_type, _BUDGETS["general"])
    return budget.get(action_type, _DEFAULT_GENERAL_LIMIT)


# ─── Queries ─────────────────────────────────────────────────────────────────

async def log_bot_action(
    conn: asyncpg.Connection,
    user_id: str,
    action_type: str,
    target_resource: str,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None,
    coordination_session_id: int | None,
) -> int:
    """Insert a bot_actions row and return its id.

    Args:
        conn: RLS-scoped asyncpg connection (app.current_user_id must be set).
        user_id: UUID string of the user on whose behalf the action is taken.
        action_type: Verb describing the mutation (e.g. 'task_created').
        target_resource: Resource path (e.g. 'tasks/123').
        before_state: JSONB snapshot before the mutation; None for INSERT ops.
        after_state: JSONB snapshot after the mutation; None for DELETE ops.
        coordination_session_id: meeting_requests.id if this action is part of
            a coordination session; None for general bot operations.

    Returns:
        The BIGSERIAL id of the newly inserted row.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO bot_actions
            (user_id, action_type, target_resource,
             before_state, after_state, coordination_session_id)
        VALUES ($1::uuid, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        user_id,
        action_type,
        target_resource,
        before_state,
        after_state,
        coordination_session_id,
    )
    return int(row["id"])


async def count_bot_actions(
    conn: asyncpg.Connection,
    user_id: str,
    action_type: str,
    since: datetime,
    coordination_session_id: int | None = None,
) -> int:
    """Count bot_actions rows matching the given criteria.

    Args:
        conn: RLS-scoped asyncpg connection.
        user_id: Filter to this user's actions.
        action_type: Filter to this action type (e.g. 'task_created').
        since: Only count rows where ts >= this timestamp.
        coordination_session_id: When provided, restrict to rows for this
            coordination session. When None, counts across all sessions.

    Returns:
        Integer count of matching rows.
    """
    if coordination_session_id is not None:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS n
            FROM bot_actions
            WHERE user_id = $1::uuid
              AND action_type = $2
              AND ts >= $3
              AND coordination_session_id = $4
            """,
            user_id,
            action_type,
            since,
            coordination_session_id,
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS n
            FROM bot_actions
            WHERE user_id = $1::uuid
              AND action_type = $2
              AND ts >= $3
            """,
            user_id,
            action_type,
            since,
        )
    return int(row["n"])


async def check_bot_budget(
    conn: asyncpg.Connection,
    user_id: str,
    coordination_session_id: int | None,
    action_type: str,
) -> bool:
    """Return True if the user is under budget for this action type.

    For coordination sessions (coordination_session_id is not None), applies
    strict limits. For general operations, applies high-but-bounded limits.
    Both modes count only rows matching (user_id, coordination_session_id,
    action_type) so that budget enforcement is scoped to the relevant context.

    Budget is zero-based: a limit of 0 means the action is never permitted
    (returns False immediately without a DB query).

    Args:
        conn: RLS-scoped asyncpg connection.
        user_id: UUID string of the acting user.
        coordination_session_id: Scopes to a coordination session when set.
        action_type: The action about to be performed.

    Returns:
        True if the action is within budget; False if the limit is reached.
    """
    session_type = "coordination" if coordination_session_id is not None else "general"
    limit = _budget_limit(action_type, session_type)

    # Zero-limit actions are never allowed — skip DB round-trip.
    if limit == 0:
        return False

    if coordination_session_id is not None:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS n
            FROM bot_actions
            WHERE user_id = $1::uuid
              AND coordination_session_id = $2
              AND action_type = $3
            """,
            user_id,
            coordination_session_id,
            action_type,
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS n
            FROM bot_actions
            WHERE user_id = $1::uuid
              AND coordination_session_id IS NULL
              AND action_type = $2
            """,
            user_id,
            action_type,
        )
    return int(row["n"]) < limit
