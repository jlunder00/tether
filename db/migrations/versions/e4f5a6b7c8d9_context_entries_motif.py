"""context_entries motif column

Adds a motif field to context_entries for visual/thematic categorization.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-04-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE context_entries ADD COLUMN motif VARCHAR(16) NOT NULL DEFAULT 'anchor'")


def downgrade() -> None:
    op.execute("ALTER TABLE context_entries DROP COLUMN IF EXISTS motif")
