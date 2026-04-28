"""Add is_all_day on tasks and preferred_timezones on users.

is_all_day — flag for all-day events (GCal all-day or UI-created all-day);
             these have no meaningful time component, only a date.
             Frontend renders them in a separate "All day" band.

preferred_timezones — up to 5 recently-used IANA timezone strings for the
                      event scheduling timezone picker; appended to when the
                      user schedules in a non-local timezone.

Note: these are column additions, not new tables, so they satisfy the
      cross-role constraint that prohibits new tables until Postgres
      migration is complete.

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-04-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All-day flag for calendar events — FALSE by default for all existing rows
    op.execute(
        "ALTER TABLE tasks ADD COLUMN is_all_day BOOLEAN NOT NULL DEFAULT FALSE"
    )

    # Preferred IANA timezone list per user — empty array by default
    op.execute(
        "ALTER TABLE users ADD COLUMN preferred_timezones TEXT[] NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS is_all_day")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS preferred_timezones")
