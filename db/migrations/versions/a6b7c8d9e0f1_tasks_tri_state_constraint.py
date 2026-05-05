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
    # Clean up pre-PR-#277 promoted tasks that violate the constraint:
    # Calendar events that still have anchor_id set (promote didn't clear it)
    op.execute("""
        UPDATE tasks SET anchor_id = NULL
        WHERE start_time IS NOT NULL AND anchor_id IS NOT NULL
    """)
    # Calendar events with no plan_date (promote didn't set it)
    op.execute("""
        UPDATE tasks SET plan_date = (start_time AT TIME ZONE 'UTC')::date
        WHERE start_time IS NOT NULL AND plan_date IS NULL
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
