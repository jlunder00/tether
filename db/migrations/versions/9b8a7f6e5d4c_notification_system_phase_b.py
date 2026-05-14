"""notification system phase B — conversations, channels, context_nodes summary

Adds the schema required for the unified notification dispatcher:
  - conversations table (with RLS)
  - conversation_history: conversation_id, source, channel columns
  - notification_channels table (with RLS)
  - context_nodes: summary, summary_updated_at columns
  - Backfills existing users' telegram_chat_id into notification_channels rows

Revision ID: 9b8a7f6e5d4c
Revises: b2c3d4e5f6a7
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "9b8a7f6e5d4c"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # §3.1  conversations table
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE conversations (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name             TEXT NOT NULL,
            type             TEXT NOT NULL DEFAULT 'interactive',
            priority         TEXT NOT NULL DEFAULT 'normal',
            state            TEXT NOT NULL DEFAULT 'open',
            context_node_id  UUID REFERENCES context_nodes(id) ON DELETE SET NULL,
            thread_key       TEXT,
            is_system        BOOLEAN NOT NULL DEFAULT false,
            created_at       TIMESTAMPTZ DEFAULT now(),
            last_message_at  TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    # Partial unique index: one open thread per (user, thread_key) when thread_key is set
    op.execute(
        """
        CREATE UNIQUE INDEX conversations_thread_key_user
            ON conversations (user_id, thread_key)
            WHERE thread_key IS NOT NULL
        """
    )

    op.execute("ALTER TABLE conversations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY conversations_isolation ON conversations
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # §3.2  conversation_history additions
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE conversation_history "
        "ADD COLUMN conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE conversation_history "
        "ADD COLUMN source TEXT NOT NULL DEFAULT 'chat'"
    )
    op.execute(
        "ALTER TABLE conversation_history "
        "ADD COLUMN channel TEXT NOT NULL DEFAULT 'telegram'"
    )
    op.execute(
        """
        CREATE INDEX conversation_history_conversation_id
            ON conversation_history (conversation_id, id DESC)
        """
    )

    # ------------------------------------------------------------------
    # §3.3  notification_channels table
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE notification_channels (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            channel_type  TEXT NOT NULL CHECK (channel_type IN ('telegram', 'web', 'discord', 'slack')),
            config        JSONB NOT NULL DEFAULT '{}',
            label         TEXT,
            enabled       BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    op.execute("ALTER TABLE notification_channels ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_channels FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY notification_channels_isolation ON notification_channels
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # §3.3 backfill: existing telegram_connections rows → notification_channels
    # telegram_chat_id lives in telegram_connections (user_id PK, telegram_chat_id TEXT).
    # Runs in the same transaction as the DDL — exactly once on deploy.
    op.execute(
        """
        INSERT INTO notification_channels (user_id, channel_type, config, label)
        SELECT
            tc.user_id,
            'telegram',
            jsonb_build_object('chat_id', tc.telegram_chat_id),
            'Telegram (migrated)'
        FROM telegram_connections tc
        ON CONFLICT DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # §3.4  context_nodes additions
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE context_nodes "
        "ADD COLUMN summary TEXT"
    )
    op.execute(
        "ALTER TABLE context_nodes "
        "ADD COLUMN summary_updated_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    # context_nodes
    op.execute("ALTER TABLE context_nodes DROP COLUMN IF EXISTS summary_updated_at")
    op.execute("ALTER TABLE context_nodes DROP COLUMN IF EXISTS summary")

    # notification_channels
    op.execute("DROP TABLE IF EXISTS notification_channels")

    # conversation_history additions
    op.execute(
        "DROP INDEX IF EXISTS conversation_history_conversation_id"
    )
    op.execute(
        "ALTER TABLE conversation_history DROP COLUMN IF EXISTS channel"
    )
    op.execute(
        "ALTER TABLE conversation_history DROP COLUMN IF EXISTS source"
    )
    op.execute(
        "ALTER TABLE conversation_history DROP COLUMN IF EXISTS conversation_id"
    )

    # conversations
    op.execute("DROP TABLE IF EXISTS conversations")
