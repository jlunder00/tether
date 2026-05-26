"""Add token_usage table to record input/output tokens per user per turn.

Feeds the trial counter display and eventual billing enforcement.
Token counts come from the agent SDK ResultMessage.usage dict, captured
on handle release by the pool manager.

Revision ID: h2b3c4d5e6f7
Revises: g1a2b3c4d5e6
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op

revision: str = "h2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "g1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE token_usage (
            id          BIGSERIAL PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            input_tokens  INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # Index for per-user rollup queries (billing, trial enforcement)
    op.execute("""
        CREATE INDEX idx_token_usage_user_id ON token_usage (user_id, recorded_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS token_usage")
