"""user_preferences table

Stores per-user key/value preferences with RLS isolation.

Revision ID: b1c2d3e4f5a6
Revises: 2a3b4c5d6e7f
Create Date: 2026-04-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "2a3b4c5d6e7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_preferences (
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key        VARCHAR(64) NOT NULL,
            value      TEXT NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (user_id, key)
        )
        """
    )
    op.execute("ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_preferences FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY user_preferences_user_isolation ON user_preferences
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_preferences")
