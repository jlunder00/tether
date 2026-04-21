"""integration data model

Adds event fields to tasks, and creates user_integrations + integration_sync_state tables.

Revision ID: a1b2c3d4e5f6
Revises: 845cab7a8515
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '845cab7a8515'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extend tasks with event/integration columns
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS start_time    TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS end_time      TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS source        TEXT NULL,
            ADD COLUMN IF NOT EXISTS external_id   TEXT NULL,
            ADD COLUMN IF NOT EXISTS external_url  TEXT NULL,
            ADD COLUMN IF NOT EXISTS source_status TEXT NULL
    """)

    # Both timestamps must be set together or both null
    op.execute("""
        ALTER TABLE tasks
            ADD CONSTRAINT tasks_start_end_both_or_null
            CHECK ((start_time IS NULL) = (end_time IS NULL))
    """)

    # Partial unique index: dedup external events per user+provider
    op.execute("""
        CREATE UNIQUE INDEX tasks_user_source_external_id_idx
            ON tasks (user_id, source, external_id)
            WHERE source IS NOT NULL
    """)

    # ------------------------------------------------------------------
    # user_integrations — OAuth tokens per user per provider
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE user_integrations (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id        TEXT NOT NULL,
            provider       TEXT NOT NULL,
            access_token   TEXT,
            refresh_token  TEXT,
            token_expiry   TIMESTAMPTZ,
            scopes         TEXT[],
            metadata       JSONB,
            enabled        BOOL NOT NULL DEFAULT true,
            last_synced_at TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, provider)
        )
    """)

    op.execute("ALTER TABLE user_integrations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_integrations FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY user_integrations_isolation ON user_integrations
            USING (user_id = current_setting('app.current_user_id', true))
    """)

    # Grant access to app role
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_integrations TO tether_app")

    # ------------------------------------------------------------------
    # integration_sync_state — one row per (integration, calendar)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE integration_sync_state (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id    UUID NOT NULL
                REFERENCES user_integrations(id) ON DELETE CASCADE,
            calendar_id       TEXT NOT NULL,
            sync_cursor       TEXT,
            watch_channel_id  TEXT,
            watch_expiry      TIMESTAMPTZ,
            watch_resource_id TEXT,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (integration_id, calendar_id)
        )
    """)

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON integration_sync_state TO tether_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS integration_sync_state")
    op.execute("DROP TABLE IF EXISTS user_integrations")
    op.execute("DROP INDEX IF EXISTS tasks_user_source_external_id_idx")
    op.execute("""
        ALTER TABLE tasks
            DROP CONSTRAINT IF EXISTS tasks_start_end_both_or_null,
            DROP COLUMN IF EXISTS source_status,
            DROP COLUMN IF EXISTS external_url,
            DROP COLUMN IF EXISTS external_id,
            DROP COLUMN IF EXISTS source,
            DROP COLUMN IF EXISTS end_time,
            DROP COLUMN IF EXISTS start_time
    """)
