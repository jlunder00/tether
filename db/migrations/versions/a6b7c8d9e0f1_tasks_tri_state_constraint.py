"""tasks tri-state constraint

Enforces the four valid task states at the DB level:
  1. Backlog:                 plan_date IS NULL  AND anchor_id IS NULL  AND start_time IS NULL
  2. Plan task:               plan_date IS NOT NULL AND anchor_id IS NOT NULL AND start_time IS NULL
  3. Calendar event:          plan_date IS NOT NULL AND anchor_id IS NULL  AND start_time IS NOT NULL
  4. Anchor-recurring master: plan_date IS NULL  AND anchor_id IS NOT NULL AND start_time IS NULL AND rrule IS NOT NULL

Precondition: run the following to verify no existing rows would be rejected:
    SELECT count(*) FROM tasks WHERE NOT (
        (plan_date IS NULL AND anchor_id IS NULL AND start_time IS NULL)
        OR (plan_date IS NOT NULL AND anchor_id IS NOT NULL AND start_time IS NULL)
        OR (plan_date IS NOT NULL AND anchor_id IS NULL AND start_time IS NOT NULL)
        OR (plan_date IS NULL AND anchor_id IS NOT NULL AND start_time IS NULL AND rrule IS NOT NULL)
    );
Expected result: 0

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-05-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Data cleanup: fix all rows that would violate the constraint ──────────
    #
    # After each UPDATE, the targeted shape is resolved into a valid case.
    # Order matters: start_time-bearing rows are fixed first so subsequent
    # checks on start_time=NULL rows are clean.

    # Case A fix: calendar events that still have anchor_id set
    # (pre-#277 promote didn't clear it) → clear anchor_id → valid Case 3
    op.execute("""
        UPDATE tasks SET anchor_id = NULL
        WHERE start_time IS NOT NULL AND anchor_id IS NOT NULL
    """)

    # Case B fix: calendar events with no plan_date
    # (pre-#277 promote didn't set it) → derive plan_date → valid Case 3
    op.execute("""
        UPDATE tasks SET plan_date = (start_time AT TIME ZONE 'UTC')::date
        WHERE start_time IS NOT NULL AND plan_date IS NULL
    """)

    # Case C fix: old plan tasks with plan_date but no anchor_id and no
    # start_time — created before anchor_id was required. Demote to backlog.
    op.execute("""
        UPDATE tasks SET plan_date = NULL
        WHERE plan_date IS NOT NULL AND anchor_id IS NULL AND start_time IS NULL
    """)

    # Case D fix: orphaned anchor assignments — anchor_id set but no plan_date,
    # no start_time, and no rrule. Cannot be any valid state; demote to backlog.
    op.execute("""
        UPDATE tasks SET anchor_id = NULL
        WHERE plan_date IS NULL AND anchor_id IS NOT NULL
          AND start_time IS NULL AND rrule IS NULL
    """)
    op.execute("""
        ALTER TABLE tasks ADD CONSTRAINT tasks_tri_state CHECK (
            -- Case 1: backlog
            (plan_date IS NULL AND anchor_id IS NULL AND start_time IS NULL)
            -- Case 2: plan task
            OR (plan_date IS NOT NULL AND anchor_id IS NOT NULL AND start_time IS NULL)
            -- Case 3: calendar event
            OR (plan_date IS NOT NULL AND anchor_id IS NULL AND start_time IS NOT NULL)
            -- Case 4: anchor-recurring master (template, no specific date)
            OR (plan_date IS NULL AND anchor_id IS NOT NULL AND start_time IS NULL AND rrule IS NOT NULL)
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_tri_state")
