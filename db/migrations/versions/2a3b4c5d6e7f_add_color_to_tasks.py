"""Add color column to tasks table.

Anchor-recurring task masters need a per-task color so the frontend
can render them with the same color affordance as regular tasks.
The column is NULL by default so existing rows are unaffected.

Revision ID: 2a3b4c5d6e7f
Revises: 1cd716bba331
Create Date: 2026-04-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "2a3b4c5d6e7f"
down_revision: Union[str, Sequence[str], None] = "1cd716bba331"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # color — optional display color for task rows (e.g. anchor-recurring masters)
    op.execute("ALTER TABLE tasks ADD COLUMN color TEXT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS color")
