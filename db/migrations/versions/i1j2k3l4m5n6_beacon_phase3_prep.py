"""Beacon Phase 3 prep — memory tables, conversation lifecycle extension

Creates the 6 Beacon memory tables per spec §5:
  - beacon_dispatches   (L1 ephemeral — per-run dispatch records)
  - beacon_decisions    (L1 — triage decision audit log)
  - beacon_suppressions (L1.5 — silent-exit suppression registry)
  - beacon_memory       (L2 — Beacon's freeform working memory)
  - beacon_durable_memory (L3 — compacted long-term patterns)
  - beacon_compaction_log (compaction audit)

All tables have:
  - user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
  - ENABLE ROW LEVEL SECURITY + FORCE ROW LEVEL SECURITY
  - Policy: USING (user_id = current_setting('app.current_user_id', true)::uuid)

Also extends conversations table:
  - handle TEXT nullable, partial unique index (user_id, handle) WHERE handle IS NOT NULL
  - expires_at TIMESTAMPTZ nullable (used by Beacon to auto-archive pending convs)

Note: the state column is TEXT; 'pending' and 'rejected' are now valid values alongside
'open' and 'closed'. No DB-level enum constraint — state validation is enforced at the
API layer (ConversationPatch Pydantic model).

Also backfills conversation_history.source:
  Any existing rows with source='notification' are updated to source='chat'.
  As of this migration the 'notification' value is deprecated — only 'chat', 'assistant',
  and 'system' are valid going forward. The backfill is idempotent.

Revision ID: i1j2k3l4m5n6
Revises: h2b3c4d5e6f7
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = "i1j2k3l4m5n6"
down_revision: Union[str, Sequence[str], None] = "h2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # L1 ephemeral — beacon_dispatches
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE beacon_dispatches (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id               UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            checkpoint_type       TEXT NOT NULL,
            mode                  TEXT NOT NULL,
            conversation_id       UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            dispatched_at         TIMESTAMPTZ DEFAULT now(),
            prompt_summary        TEXT,
            priority              TEXT NOT NULL DEFAULT 'normal',
            dispatched_agent_role TEXT NOT NULL DEFAULT 'default',
            state                 TEXT NOT NULL DEFAULT 'active',
            last_message_at       TIMESTAMPTZ,
            concluded_at          TIMESTAMPTZ,
            evaluated_at          TIMESTAMPTZ,
            rejection_memory_key  TEXT,
            notes                 TEXT
        )
        """
    )
    op.execute(
        """
        CREATE INDEX beacon_dispatches_active
            ON beacon_dispatches (user_id, state)
            WHERE state = 'active'
        """
    )
    op.execute(
        """
        CREATE INDEX beacon_dispatches_pending_eval
            ON beacon_dispatches (concluded_at)
            WHERE state = 'concluded' AND evaluated_at IS NULL
        """
    )
    op.execute("ALTER TABLE beacon_dispatches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE beacon_dispatches FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY beacon_dispatches_isolation ON beacon_dispatches
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # L1 ephemeral — beacon_decisions
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE beacon_decisions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            checkpoint_type TEXT NOT NULL,
            mode            TEXT NOT NULL,
            decided_at      TIMESTAMPTZ DEFAULT now(),
            action          TEXT NOT NULL,
            reason          TEXT,
            beacon_run_id   UUID
        )
        """
    )
    op.execute(
        """
        CREATE INDEX beacon_decisions_user_recent
            ON beacon_decisions (user_id, decided_at DESC)
        """
    )
    op.execute("ALTER TABLE beacon_decisions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE beacon_decisions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY beacon_decisions_isolation ON beacon_decisions
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # L1.5 — beacon_suppressions
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE beacon_suppressions (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            scope_key   TEXT NOT NULL,
            reason      TEXT,
            source      TEXT NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT now(),
            expires_at  TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX beacon_suppressions_lookup
            ON beacon_suppressions (user_id, scope_key)
            WHERE expires_at IS NULL OR expires_at > now()
        """
    )
    op.execute("ALTER TABLE beacon_suppressions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE beacon_suppressions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY beacon_suppressions_isolation ON beacon_suppressions
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # L2 — beacon_memory (Beacon's freeform working memory)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE beacon_memory (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key          TEXT NOT NULL,
            value        TEXT NOT NULL,
            updated_at   TIMESTAMPTZ DEFAULT now(),
            last_read_at TIMESTAMPTZ,
            UNIQUE (user_id, key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX beacon_memory_user_key
            ON beacon_memory (user_id, key text_pattern_ops)
        """
    )
    op.execute("ALTER TABLE beacon_memory ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE beacon_memory FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY beacon_memory_isolation ON beacon_memory
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # L3 — beacon_durable_memory (compacted long-term patterns)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE beacon_durable_memory (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key         TEXT NOT NULL,
            value       TEXT NOT NULL,
            source      TEXT NOT NULL,
            evidence    JSONB,
            confidence  TEXT DEFAULT 'medium',
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now(),
            UNIQUE (user_id, key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX beacon_durable_memory_user_key
            ON beacon_durable_memory (user_id, key text_pattern_ops)
        """
    )
    op.execute("ALTER TABLE beacon_durable_memory ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE beacon_durable_memory FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY beacon_durable_memory_isolation ON beacon_durable_memory
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # Compaction audit log
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE beacon_compaction_log (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            trigger_type     TEXT NOT NULL,
            started_at       TIMESTAMPTZ DEFAULT now(),
            completed_at     TIMESTAMPTZ,
            surfaces_touched JSONB,
            tokens_before    INT,
            tokens_after     INT,
            notes            TEXT
        )
        """
    )
    op.execute("ALTER TABLE beacon_compaction_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE beacon_compaction_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY beacon_compaction_log_isolation ON beacon_compaction_log
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # conversations table extension (spec §7.4)
    # handle: slug for @-routing, unique per user when set
    # expires_at: Beacon uses this to auto-archive pending convs
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE conversations ADD COLUMN handle TEXT"
    )
    op.execute(
        "ALTER TABLE conversations ADD COLUMN expires_at TIMESTAMPTZ"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX conversations_handle_user
            ON conversations (user_id, handle)
            WHERE handle IS NOT NULL
        """
    )

    # ------------------------------------------------------------------
    # Backfill conversation_history.source (spec §8.3)
    # 'notification' is deprecated — rows that carry it are updated to 'chat'.
    # The backfill is idempotent: re-running on a clean DB is a no-op.
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE conversation_history
        SET source = 'chat'
        WHERE source = 'notification'
        """
    )


def downgrade() -> None:
    # conversations extensions
    op.execute("DROP INDEX IF EXISTS conversations_handle_user")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS expires_at")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS handle")

    # Beacon tables (reverse creation order — foreign-key safe)
    op.execute("DROP TABLE IF EXISTS beacon_compaction_log")
    op.execute("DROP TABLE IF EXISTS beacon_durable_memory")
    op.execute("DROP TABLE IF EXISTS beacon_memory")
    op.execute("DROP TABLE IF EXISTS beacon_suppressions")
    op.execute("DROP TABLE IF EXISTS beacon_decisions")
    op.execute("DROP TABLE IF EXISTS beacon_dispatches")
