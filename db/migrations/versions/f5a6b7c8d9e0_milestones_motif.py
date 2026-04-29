"""milestones motif column

Adds a motif field to milestones for visual/thematic categorization.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-04-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE milestones ADD COLUMN motif VARCHAR(16) NOT NULL DEFAULT 'anchor'")


def downgrade() -> None:
    op.execute("ALTER TABLE milestones DROP COLUMN IF EXISTS motif")
