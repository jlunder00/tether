"""Unit tests for dynamic-SQL allowlist guards in pg_queries.

These tests verify that patch/update functions:
- Reject unknown field names (return None / no-op)
- Never allow user-controlled strings to flow into SQL column names

These are pure-Python unit tests — they do NOT need a live Postgres
connection because they exercise the field-filtering logic before
any SQL is constructed.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# patch_task_fields — unknown fields are silently ignored, returns None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_task_fields_rejects_unknown_fields():
    """patch_task_fields returns None when no valid field names are supplied."""
    from db.pg_queries.tasks import patch_task_fields

    # Simulate the early-return guard by checking allowed fields manually.
    # The real function would need a DB conn; here we just verify the guard
    # logic by calling with a mock connection that should never be used.
    class NeverCalledConn:
        async def execute(self, *a, **kw):
            raise AssertionError("SQL should not be executed for empty updates")
        async def fetchval(self, *a, **kw):
            raise AssertionError("SQL should not be executed for empty updates")
        async def fetchrow(self, *a, **kw):
            raise AssertionError("SQL should not be executed for empty updates")
        async def fetch(self, *a, **kw):
            raise AssertionError("SQL should not be executed for empty updates")

    result = await patch_task_fields(
        NeverCalledConn(),  # type: ignore[arg-type]
        "00000000-0000-0000-0000-000000000001",
        {"'; DROP TABLE tasks; --": "evil", "nonexistent_col": "bad"},
    )
    assert result is None, "Should return None when no valid fields supplied"


# ---------------------------------------------------------------------------
# update_subtask — unknown fields produce no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_subtask_rejects_unknown_fields():
    """update_subtask is a no-op when no valid field names are supplied."""
    from db.pg_queries.tasks import update_subtask

    class NeverCalledConn:
        async def execute(self, *a, **kw):
            raise AssertionError("SQL should not be executed for empty updates")

    # Should return None (no-op) without touching the DB
    result = await update_subtask(
        NeverCalledConn(),  # type: ignore[arg-type]
        subtask_id=1,
        malicious_col="'; DROP TABLE subtasks; --",
        nonexistent="bad",
    )
    assert result is None


# ---------------------------------------------------------------------------
# update_kanban_column — unknown fields produce None return
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_kanban_column_rejects_unknown_fields():
    """update_kanban_column returns None when no valid fields are supplied."""
    from db.pg_queries.kanban import update_kanban_column

    class NeverCalledConn:
        async def execute(self, *a, **kw):
            raise AssertionError("SQL should not be executed for empty updates")

    result = await update_kanban_column(
        NeverCalledConn(),  # type: ignore[arg-type]
        column_id="00000000-0000-0000-0000-000000000001",
        fields={"'; DROP TABLE kanban_columns; --": "evil"},
    )
    assert result is None


# ---------------------------------------------------------------------------
# patch_milestone — unknown fields produce None return
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_milestone_rejects_unknown_fields():
    """patch_milestone returns None when no valid fields are supplied."""
    from db.pg_queries.milestones import patch_milestone

    class NeverCalledConn:
        async def execute(self, *a, **kw):
            raise AssertionError("SQL should not be executed for empty updates")

    result = await patch_milestone(
        NeverCalledConn(),  # type: ignore[arg-type]
        milestone_id="00000000-0000-0000-0000-000000000001",
        fields={"'; DROP TABLE milestones; --": "evil"},
    )
    assert result is None
