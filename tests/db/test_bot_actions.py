"""Tests for bot_actions DB queries — log, count, budget enforcement.

Tests require DATABASE_URL env var pointing to a live Postgres instance
with the bot_actions migration applied.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import asyncpg
import pytest

from db.postgres import register_jsonb_codec
from tests.db.pg_conftest import conn, auth_conn  # noqa: F401
from db.pg_queries.bot_actions import (
    log_bot_action,
    count_bot_actions,
    check_bot_budget,
)

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"

pytestmark = pytest.mark.asyncio


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — Postgres tests skipped")
    return url


async def _ensure_other_user(url: str) -> None:
    """Seed a second test user outside the rolled-back transaction."""
    c = await asyncpg.connect(dsn=url)
    try:
        await c.execute(
            """
            INSERT INTO users (id, username, email, password_hash, is_admin)
            VALUES ($1::uuid, 'otheruser', 'other@example.com', 'x', false)
            ON CONFLICT (id) DO NOTHING
            """,
            OTHER_USER_ID,
        )
    finally:
        await c.close()


# ──────────────────────────────────────────────────────────────────────────────
# Schema / migration sanity
# ──────────────────────────────────────────────────────────────────────────────

async def test_bot_actions_table_exists(conn):
    """Migration must have created the bot_actions table with expected columns."""
    row = await conn.fetchrow(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'bot_actions'
        ORDER BY ordinal_position
        """
    )
    # If no row, the table doesn't exist at all.
    assert row is not None, "bot_actions table does not exist"


async def test_bot_actions_has_required_columns(conn):
    """All required columns must be present with correct types."""
    rows = await conn.fetch(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'bot_actions'
        """
    )
    cols = {r["column_name"]: r for r in rows}
    assert "id" in cols
    assert "user_id" in cols
    assert "action_type" in cols
    assert "target_resource" in cols
    assert "before_state" in cols
    assert "after_state" in cols
    assert "coordination_session_id" in cols
    assert "ts" in cols

    assert cols["user_id"]["is_nullable"] == "NO"
    assert cols["action_type"]["is_nullable"] == "NO"
    assert cols["target_resource"]["is_nullable"] == "NO"
    # Nullable columns
    assert cols["before_state"]["is_nullable"] == "YES"
    assert cols["after_state"]["is_nullable"] == "YES"
    assert cols["coordination_session_id"]["is_nullable"] == "YES"


async def test_bot_actions_rls_enabled(auth_conn):
    """RLS must be enabled on bot_actions."""
    row = await auth_conn.fetchrow(
        "SELECT relrowsecurity FROM pg_class WHERE relname = 'bot_actions'"
    )
    assert row is not None, "bot_actions table not found in pg_class"
    assert row["relrowsecurity"] is True, "RLS not enabled on bot_actions"


# ──────────────────────────────────────────────────────────────────────────────
# log_bot_action
# ──────────────────────────────────────────────────────────────────────────────

async def test_log_bot_action_returns_id(conn):
    """log_bot_action must insert a row and return an integer id."""
    action_id = await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/123",
        before_state=None,
        after_state={"text": "meeting", "status": "pending"},
        coordination_session_id=None,
    )
    assert isinstance(action_id, int)
    assert action_id > 0


async def test_log_bot_action_row_visible_to_owner(conn):
    """The owner must be able to see the inserted row via RLS."""
    action_id = await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/42",
        before_state=None,
        after_state={"status": "pending"},
        coordination_session_id=None,
    )
    row = await conn.fetchrow(
        "SELECT id, action_type, target_resource FROM bot_actions WHERE id = $1",
        action_id,
    )
    assert row is not None
    assert row["action_type"] == "task_created"
    assert row["target_resource"] == "tasks/42"


async def test_log_bot_action_with_before_and_after_state(conn):
    """before_state and after_state JSONB fields must round-trip correctly."""
    before = {"status": "pending", "text": "old text"}
    after = {"status": "completed", "text": "new text"}
    action_id = await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_updated",
        target_resource="tasks/99",
        before_state=before,
        after_state=after,
        coordination_session_id=None,
    )
    row = await conn.fetchrow(
        "SELECT before_state, after_state FROM bot_actions WHERE id = $1",
        action_id,
    )
    assert row["before_state"] == before
    assert row["after_state"] == after


async def test_log_bot_action_with_coordination_session_id(conn):
    """coordination_session_id must be stored and queryable."""
    session_id = 7  # bigint (meeting_requests.id)
    action_id = await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/77",
        before_state=None,
        after_state={"status": "pending"},
        coordination_session_id=session_id,
    )
    row = await conn.fetchrow(
        "SELECT coordination_session_id FROM bot_actions WHERE id = $1",
        action_id,
    )
    assert row["coordination_session_id"] == session_id


# ──────────────────────────────────────────────────────────────────────────────
# RLS isolation
# ──────────────────────────────────────────────────────────────────────────────

async def test_rls_blocks_cross_user_read():
    """User B must not see User A's bot_actions rows."""
    url = _db_url()
    await _ensure_other_user(url)

    action_id = None
    conn_a = await asyncpg.connect(dsn=url)
    await register_jsonb_codec(conn_a)
    tr_a = conn_a.transaction()
    await tr_a.start()
    try:
        await conn_a.execute(
            "SELECT set_config('app.current_user_id', $1, true)", TEST_USER_ID
        )
        action_id = await log_bot_action(
            conn_a,
            user_id=TEST_USER_ID,
            action_type="task_created",
            target_resource="tasks/rls-test",
            before_state=None,
            after_state=None,
            coordination_session_id=None,
        )
        await tr_a.commit()
    except Exception:
        await tr_a.rollback()
        raise
    finally:
        await conn_a.close()

    # User B should not see the row
    conn_b = await asyncpg.connect(dsn=url)
    await register_jsonb_codec(conn_b)
    tr_b = conn_b.transaction()
    await tr_b.start()
    try:
        await conn_b.execute(
            "SELECT set_config('app.current_user_id', $1, true)", OTHER_USER_ID
        )
        row = await conn_b.fetchrow(
            "SELECT id FROM bot_actions WHERE id = $1", action_id
        )
        assert row is None, "User B can see User A's bot_actions row — RLS not enforced"
    finally:
        await tr_b.rollback()
        await conn_b.close()

    # Cleanup
    cleanup = await asyncpg.connect(dsn=url)
    try:
        await cleanup.execute("DELETE FROM bot_actions WHERE id = $1", action_id)
    finally:
        await cleanup.close()


# ──────────────────────────────────────────────────────────────────────────────
# count_bot_actions
# ──────────────────────────────────────────────────────────────────────────────

async def test_count_bot_actions_basic(conn):
    """count_bot_actions must return the correct count for a user + type."""
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    # Insert 2 task_created, 1 task_updated
    for _ in range(2):
        await log_bot_action(
            conn,
            user_id=TEST_USER_ID,
            action_type="task_created",
            target_resource="tasks/x",
            before_state=None,
            after_state=None,
            coordination_session_id=None,
        )
    await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_updated",
        target_resource="tasks/x",
        before_state=None,
        after_state=None,
        coordination_session_id=None,
    )

    count = await count_bot_actions(
        conn, user_id=TEST_USER_ID, action_type="task_created", since=since
    )
    assert count == 2

    count_updated = await count_bot_actions(
        conn, user_id=TEST_USER_ID, action_type="task_updated", since=since
    )
    assert count_updated == 1


async def test_count_bot_actions_filters_by_time_window(conn):
    """count_bot_actions must exclude rows older than `since`."""
    future_since = datetime.now(timezone.utc) + timedelta(hours=1)
    await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/old",
        before_state=None,
        after_state=None,
        coordination_session_id=None,
    )
    count = await count_bot_actions(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        since=future_since,
    )
    assert count == 0


async def test_count_bot_actions_filters_by_session(conn):
    """When coordination_session_id is provided, only count rows for that session."""
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    session_id = 42

    # One in-session, one not
    await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/s",
        before_state=None,
        after_state=None,
        coordination_session_id=session_id,
    )
    await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/ns",
        before_state=None,
        after_state=None,
        coordination_session_id=None,
    )

    count_session = await count_bot_actions(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        since=since,
        coordination_session_id=session_id,
    )
    assert count_session == 1


async def test_count_bot_actions_no_session_counts_all(conn):
    """When coordination_session_id is None, count all actions regardless of session."""
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/a",
        before_state=None,
        after_state=None,
        coordination_session_id=99,
    )
    await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/b",
        before_state=None,
        after_state=None,
        coordination_session_id=None,
    )
    count = await count_bot_actions(
        conn, user_id=TEST_USER_ID, action_type="task_created", since=since
    )
    assert count == 2


# ──────────────────────────────────────────────────────────────────────────────
# check_bot_budget
# ──────────────────────────────────────────────────────────────────────────────

async def test_check_bot_budget_returns_true_when_under_limit(conn):
    """check_bot_budget must return True when no actions have been logged yet."""
    result = await check_bot_budget(
        conn,
        user_id=TEST_USER_ID,
        coordination_session_id=None,
        action_type="task_created",
    )
    assert result is True


async def test_check_bot_budget_non_coordination_allows_multiple_creates(conn):
    """General (non-coordination) budget allows up to 10 task_created actions."""
    since_start = datetime.now(timezone.utc) - timedelta(minutes=1)
    for i in range(10):
        # Log 10 task_created; budget should still allow the 11th to fail
        await log_bot_action(
            conn,
            user_id=TEST_USER_ID,
            action_type="task_created",
            target_resource=f"tasks/{i}",
            before_state=None,
            after_state=None,
            coordination_session_id=None,
        )

    # After 10, budget is exhausted
    result = await check_bot_budget(
        conn,
        user_id=TEST_USER_ID,
        coordination_session_id=None,
        action_type="task_created",
    )
    assert result is False


async def test_check_bot_budget_returns_false_when_over_limit(conn):
    """check_bot_budget returns False once the action count reaches the limit."""
    session_id = 55
    # Coordination budget: task_created = 1
    await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/m",
        before_state=None,
        after_state=None,
        coordination_session_id=session_id,
    )
    result = await check_bot_budget(
        conn,
        user_id=TEST_USER_ID,
        coordination_session_id=session_id,
        action_type="task_created",
    )
    assert result is False


async def test_check_bot_budget_coordination_stricter_than_non_coordination(conn):
    """Coordination sessions have strictly tighter limits than general sessions."""
    session_id = 66
    # Log 2 task_created for general (no session) — should still be under limit
    for i in range(2):
        await log_bot_action(
            conn,
            user_id=TEST_USER_ID,
            action_type="task_created",
            target_resource=f"tasks/gen{i}",
            before_state=None,
            after_state=None,
            coordination_session_id=None,
        )
    general_ok = await check_bot_budget(
        conn,
        user_id=TEST_USER_ID,
        coordination_session_id=None,
        action_type="task_created",
    )
    assert general_ok is True, "General budget should allow 2 task_created"

    # Log 1 task_created for this coordination session — should hit limit
    await log_bot_action(
        conn,
        user_id=TEST_USER_ID,
        action_type="task_created",
        target_resource="tasks/coord",
        before_state=None,
        after_state=None,
        coordination_session_id=session_id,
    )
    coord_ok = await check_bot_budget(
        conn,
        user_id=TEST_USER_ID,
        coordination_session_id=session_id,
        action_type="task_created",
    )
    assert coord_ok is False, "Coordination budget limit (1) should be exhausted"


async def test_check_bot_budget_task_update_zero_in_coordination(conn):
    """Coordination budget for task_updated is 0 — always False after first log."""
    session_id = 77
    # Even without any logged task_updated, budget should be exhausted (limit=0 means never allowed)
    result = await check_bot_budget(
        conn,
        user_id=TEST_USER_ID,
        coordination_session_id=session_id,
        action_type="task_updated",
    )
    assert result is False, "task_updated limit in coordination is 0 — should be False"


async def test_check_bot_budget_task_delete_zero_in_coordination(conn):
    """Coordination budget for task_deleted is 0 — always False."""
    session_id = 88
    result = await check_bot_budget(
        conn,
        user_id=TEST_USER_ID,
        coordination_session_id=session_id,
        action_type="task_deleted",
    )
    assert result is False, "task_deleted limit in coordination is 0 — should be False"


async def test_check_bot_budget_task_delete_allowed_in_general(conn):
    """Non-coordination budget allows up to 5 task_deleted."""
    # Zero deletions so far — should be True
    result = await check_bot_budget(
        conn,
        user_id=TEST_USER_ID,
        coordination_session_id=None,
        action_type="task_deleted",
    )
    assert result is True
