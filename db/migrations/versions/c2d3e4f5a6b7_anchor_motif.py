"""anchor motif column

Adds a motif field to anchors for visual/thematic categorization.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-04-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE anchors ADD COLUMN motif VARCHAR(16) NOT NULL DEFAULT 'anchor'")


def downgrade() -> None:
    op.execute("ALTER TABLE anchors DROP COLUMN IF EXISTS motif")
