"""Tests for db/pg_queries/followup.py — ON CONFLICT clause bug regression."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Bug A: ON CONFLICT must use (user_id, date, task_id) — not anchor_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_init_followup_state_sql_excludes_anchor_id():
    """init_followup_state must use ON CONFLICT (user_id, date, task_id).

    The followup_state table has UNIQUE (user_id, date, task_id).
    Including anchor_id in the ON CONFLICT clause raises a Postgres error
    because no such constraint exists — this is the root cause of task pings
    never firing (get_active_followup_states always returned empty).
    """
    from db.pg_queries.followup import init_followup_state

    mock_conn = AsyncMock()
    now = datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc)

    await init_followup_state(
        conn=mock_conn,
        date="2026-05-05",
        anchor_id="anchor-abc",
        task_id="task-xyz",
        now=now,
    )

    assert mock_conn.execute.called, "execute should be called"
    sql_arg = mock_conn.execute.call_args[0][0]

    # Must NOT reference anchor_id in the ON CONFLICT clause
    import re
    # Extract the ON CONFLICT portion
    on_conflict_match = re.search(
        r"ON CONFLICT\s*\(([^)]+)\)", sql_arg, re.IGNORECASE
    )
    assert on_conflict_match, "ON CONFLICT clause not found in SQL"
    conflict_cols = [c.strip() for c in on_conflict_match.group(1).split(",")]

    assert "anchor_id" not in conflict_cols, (
        f"anchor_id must NOT appear in ON CONFLICT columns — "
        f"table unique constraint is (user_id, date, task_id). "
        f"Got: {conflict_cols}"
    )
    assert "user_id" in conflict_cols, "user_id must be in ON CONFLICT"
    assert "date" in conflict_cols, "date must be in ON CONFLICT"
    assert "task_id" in conflict_cols, "task_id must be in ON CONFLICT"
