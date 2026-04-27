"""rrule recurrence columns on tasks

Store recurring Google Calendar events as a single task row per series,
with RRULE string for occurrence expansion at query time.

Revision ID: e1f2a3b4c5d6
Revises: d2e3f4a5b6c7
Create Date: 2026-04-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # rrule — RRULE string for recurring series master rows (e.g. "RRULE:FREQ=WEEKLY;BYDAY=MO")
    op.execute("ALTER TABLE tasks ADD COLUMN rrule TEXT NULL")

    # recurrence_id — GCal recurringEventId for one-off exception instances
    op.execute("ALTER TABLE tasks ADD COLUMN recurrence_id TEXT NULL")

    # exdates — excluded dates from the series (ISO date strings)
    op.execute("ALTER TABLE tasks ADD COLUMN exdates TEXT[] NULL DEFAULT '{}'")

    # Partial index for fast lookups of exception instances by series
    op.execute(
        "CREATE INDEX tasks_recurrence_id_idx ON tasks(user_id, recurrence_id)"
        " WHERE recurrence_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS tasks_recurrence_id_idx")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS exdates")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS recurrence_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS rrule")
