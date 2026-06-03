"""Memory-context v2 schema additions.

Adds the infrastructure required for agent memory + context access system:

1. node_sections gains:
   - origin TEXT NOT NULL DEFAULT 'user'
     Tracks who wrote the section: 'user' | 'conversation_agent' | 'system'
   - visible_to_user BOOL NOT NULL DEFAULT true
     Controls whether the section surfaces in user-facing context reads.
     Bot-internal notes (origin='conversation_agent', visible_to_user=false)
     are hidden from the UI but readable by agents with the right scope.

2. node_data_summary — M-level summarization cache per node.
   Beacon populates this table (Stream D); agents read from it (Stream A tools).
   Each row is one M-level for one node. value carries the full key tree at
   that level: {keys: {key_name: {value, expands_to_M(k+1)}}}.
   Degrades gracefully when no rows exist (tools fall back to node_sections).

3. user_memory — L2 working memory for user facts/patterns/preferences.
   Written by Beacon; read by interactive 2.5 agents at session start.
   Mirrored from beacon_memory (Beacon spec §5.1).

4. user_durable_memory — L3 compacted long-term user patterns.
   Written by Beacon compaction only (monthly+).
   Mirrored from beacon_durable_memory (Beacon spec §5.1).

5. pending_memory_writes — staging table for propose_user_memory_write.
   MCP tool propose_user_memory_write() inserts here; Beacon evaluator
   reviews and commits or discards after the conversation concludes.

6. node_read_log — read-credit tracking per conversation.
   Every read_context / read_node_memory call inserts a row.
   write_node_memory consults this table for advisory read-before-write check
   (v1: warns on violation; v2: hard block once Stream C is stable).

All new tables have:
  - ENABLE ROW LEVEL SECURITY
  - FORCE ROW LEVEL SECURITY
  - USING (user_id = current_setting('app.current_user_id', true)::uuid)

Revision ID: k1l2m3n4o5p6
Revises: j1k2l3m4n5o6
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, Sequence[str], None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. node_sections — add origin + visible_to_user                     #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        ALTER TABLE node_sections
            ADD COLUMN origin TEXT NOT NULL DEFAULT 'user',
            ADD COLUMN visible_to_user BOOL NOT NULL DEFAULT true
        """
    )

    # ------------------------------------------------------------------ #
    # 2. node_data_summary                                                #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE node_data_summary (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            node_id          UUID NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
            level_ordinal    INT  NOT NULL,
            value            JSONB NOT NULL,
            abstract         TEXT,
            source_checksum  TEXT NOT NULL,
            generated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (node_id, level_ordinal)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_node_data_summary_node ON node_data_summary (node_id)"
    )
    op.execute(
        "CREATE INDEX idx_node_data_summary_user ON node_data_summary (user_id)"
    )
    op.execute("ALTER TABLE node_data_summary ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE node_data_summary FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY node_data_summary_isolation ON node_data_summary
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------ #
    # 3. user_memory (L2 — working memory for user facts/patterns)        #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE user_memory (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key          TEXT NOT NULL,
            value        TEXT NOT NULL,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_read_at TIMESTAMPTZ,
            UNIQUE (user_id, key)
        )
        """
    )
    op.execute(
        "CREATE INDEX user_memory_user_key ON user_memory (user_id, key text_pattern_ops)"
    )
    op.execute("ALTER TABLE user_memory ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_memory FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY user_memory_isolation ON user_memory
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------ #
    # 4. user_durable_memory (L3 — compacted long-term user patterns)     #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE user_durable_memory (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key         TEXT NOT NULL,
            value       TEXT NOT NULL,
            source      TEXT NOT NULL,
            evidence    JSONB,
            confidence  TEXT NOT NULL DEFAULT 'medium',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, key)
        )
        """
    )
    op.execute(
        "CREATE INDEX user_durable_memory_user_key ON user_durable_memory (user_id, key text_pattern_ops)"
    )
    op.execute("ALTER TABLE user_durable_memory ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_durable_memory FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY user_durable_memory_isolation ON user_durable_memory
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------ #
    # 5. pending_memory_writes — staging for propose_user_memory_write    #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE pending_memory_writes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
            key             TEXT NOT NULL,
            value           TEXT NOT NULL,
            reason          TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewed_at     TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX pending_memory_writes_user_status ON pending_memory_writes (user_id, status)"
    )
    op.execute("ALTER TABLE pending_memory_writes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pending_memory_writes FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY pending_memory_writes_isolation ON pending_memory_writes
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------ #
    # 6. node_read_log — per-conversation read-credit tracking            #
    # ------------------------------------------------------------------ #
    op.execute(
        """
        CREATE TABLE node_read_log (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
            node_id         UUID NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
            level_ordinal   INT  NOT NULL,
            title           TEXT,
            read_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX node_read_log_conv_node ON node_read_log
            (conversation_id, node_id, level_ordinal)
        """
    )
    op.execute(
        "CREATE INDEX node_read_log_user ON node_read_log (user_id)"
    )
    op.execute("ALTER TABLE node_read_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE node_read_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY node_read_log_isolation ON node_read_log
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS node_read_log")
    op.execute("DROP TABLE IF EXISTS pending_memory_writes")
    op.execute("DROP TABLE IF EXISTS user_durable_memory")
    op.execute("DROP TABLE IF EXISTS user_memory")
    op.execute("DROP TABLE IF EXISTS node_data_summary")
    op.execute(
        """
        ALTER TABLE node_sections
            DROP COLUMN IF EXISTS visible_to_user,
            DROP COLUMN IF EXISTS origin
        """
    )
