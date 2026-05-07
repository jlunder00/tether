"""bot_actions audit table for bot action tracking and budget enforcement

Revision ID: b2c3d4e5f6a7
Revises: a6b7c8d9e0f1
Create Date: 2026-05-07

Records every write action performed by the bot on behalf of a user.
Provides:
  - Full audit trail with before/after JSONB diffs
  - RLS isolation (users see only their own rows)
  - Foundation for per-session budget enforcement

Budget enforcement: count rows per (user_id, coordination_session_id, action_type)
and compare against limits defined in db/pg_queries/bot_actions.py.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE bot_actions (
            id                      BIGSERIAL PRIMARY KEY,
            user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action_type             TEXT NOT NULL,
            target_resource         TEXT NOT NULL,
            before_state            JSONB,
            after_state             JSONB,
            coordination_session_id BIGINT REFERENCES meeting_requests(id) ON DELETE SET NULL,
            ts                      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # RLS — users see only their own bot_actions rows
    op.execute("ALTER TABLE bot_actions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE bot_actions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY bot_actions_user_select ON bot_actions
            FOR SELECT
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
    """)
    op.execute("""
        CREATE POLICY bot_actions_user_insert ON bot_actions
            FOR INSERT
            WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid)
    """)

    # Indexes
    op.execute("""
        CREATE INDEX bot_actions_user_ts_idx
            ON bot_actions (user_id, ts DESC)
    """)
    op.execute("""
        CREATE INDEX bot_actions_session_idx
            ON bot_actions (coordination_session_id)
            WHERE coordination_session_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS bot_actions_session_idx")
    op.execute("DROP INDEX IF EXISTS bot_actions_user_ts_idx")
    op.execute("DROP POLICY IF EXISTS bot_actions_user_insert ON bot_actions")
    op.execute("DROP POLICY IF EXISTS bot_actions_user_select ON bot_actions")
    op.execute("DROP TABLE IF EXISTS bot_actions")
