"""Add premium_trial_usage table for tether-agent-2.5 free-trial counter.

Revision ID: g1a2b3c4d5e6
Revises: f5a6b7c8d9e0
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op

revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE premium_trial_usage (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            year_month TEXT NOT NULL,
            used_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, year_month)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS premium_trial_usage")
