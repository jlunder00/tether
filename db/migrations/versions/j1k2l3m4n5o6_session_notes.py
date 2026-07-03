"""Add session_notes table — singleton per-user storage for bot session summaries.

Replaces the previous pattern of writing to ~/.tether-config/.session-notes.md,
which breaks in Fly containers due to filesystem permissions. The table holds one
row per user; content is accumulated across sessions (append) or rewritten (LLM
summarization pass) by tether-premium's memory pipeline.

Design:
  - user_id UUID PRIMARY KEY — singleton row, user is the natural key
  - content TEXT NOT NULL DEFAULT '' — empty string is a valid reset state
  - updated_at TIMESTAMPTZ — refreshed on every upsert for auditing/expiry

Security:
  - ENABLE ROW LEVEL SECURITY + FORCE ROW LEVEL SECURITY
  - Policy: USING (user_id = current_setting('app.current_user_id', true)::uuid)
  - ON DELETE CASCADE from users table — notes are cleaned up when user is deleted

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2026-05-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, Sequence[str], None] = "i1j2k3l4m5n6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE session_notes (
            user_id    UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            content    TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE session_notes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE session_notes FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY session_notes_isolation ON session_notes
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS session_notes")
