"""tasks tri-state constraint

Enforces the three valid task states at the DB level:
  1. Backlog:        start_time IS NULL  AND plan_date IS NULL  AND anchor_id IS NULL
  2. Plan task:      start_time IS NULL  AND plan_date IS NOT NULL AND anchor_id IS NOT NULL
  3. Calendar event: start_time IS NOT NULL AND plan_date IS NOT NULL AND anchor_id IS NULL

Precondition: run the following to verify no existing rows would be rejected:
    SELECT count(*) FROM tasks WHERE NOT (
        (start_time IS NULL AND plan_date IS NULL AND anchor_id IS NULL)
        OR (start_time IS NULL AND plan_date IS NOT NULL AND anchor_id IS NOT NULL)
        OR (start_time IS NOT NULL AND plan_date IS NOT NULL AND anchor_id IS NULL)
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
    op.execute("""
        ALTER TABLE tasks ADD CONSTRAINT tasks_tri_state CHECK (
            (start_time IS NULL AND plan_date IS NULL AND anchor_id IS NULL)
            OR (start_time IS NULL AND plan_date IS NOT NULL AND anchor_id IS NOT NULL)
            OR (start_time IS NOT NULL AND plan_date IS NOT NULL AND anchor_id IS NULL)
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_tri_state")
