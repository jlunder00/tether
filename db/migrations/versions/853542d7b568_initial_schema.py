"""initial schema

Revision ID: 853542d7b568
Revises:
Create Date: 2026-04-16 22:59:47.663426

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '853542d7b568'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # ── Auth tables (no user_id — global) ─────────────────────────────────────

    op.execute("""
        CREATE TABLE users (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username     TEXT UNIQUE NOT NULL,
            email        TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            is_admin     BOOLEAN NOT NULL DEFAULT FALSE,
            created_at   TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE oauth_connections (
            user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider         TEXT NOT NULL,
            provider_user_id TEXT NOT NULL,
            access_token     TEXT,
            refresh_token    TEXT,
            UNIQUE(provider, provider_user_id)
        )
    """)

    op.execute("""
        CREATE TABLE invite_tokens (
            token      TEXT PRIMARY KEY,
            created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            used_by    UUID REFERENCES users(id) ON DELETE SET NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE telegram_connections (
            user_id         UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            telegram_chat_id TEXT UNIQUE NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE telegram_link_codes (
            code             TEXT PRIMARY KEY,
            telegram_chat_id TEXT NOT NULL,
            created_at       TIMESTAMPTZ DEFAULT now()
        )
    """)

    # ── User-data tables (all have user_id UUID FK + RLS) ─────────────────────

    op.execute("""
        CREATE TABLE anchors (
            id               UUID PRIMARY KEY,
            user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name             TEXT NOT NULL,
            time             TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            flexibility      TEXT NOT NULL DEFAULT 'flexible',
            strictness       INTEGER NOT NULL DEFAULT 3,
            color            TEXT NOT NULL DEFAULT '#888888',
            position         INTEGER NOT NULL DEFAULT 0,
            followup_config  JSONB
        )
    """)

    op.execute("""
        CREATE TABLE plans (
            date    TEXT NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            version INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (date, user_id)
        )
    """)

    op.execute("""
        CREATE TABLE tasks (
            id              BIGSERIAL PRIMARY KEY,
            uuid            UUID NOT NULL DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            plan_date       TEXT,
            anchor_id       UUID,
            position        INTEGER NOT NULL DEFAULT 0,
            text            TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            followup_config JSONB,
            notes           TEXT NOT NULL DEFAULT '',
            description     TEXT,
            context_subject TEXT,
            context_node_id UUID,
            version         INTEGER NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
        CREATE TABLE task_dependencies (
            task_id       UUID NOT NULL,
            blocked_by_id UUID NOT NULL,
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (task_id, blocked_by_id)
        )
    """)

    op.execute("""
        CREATE TABLE dependencies (
            id           BIGSERIAL PRIMARY KEY,
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            blocker_type TEXT NOT NULL,
            blocker_id   TEXT NOT NULL,
            blocked_type TEXT NOT NULL,
            blocked_id   TEXT NOT NULL,
            UNIQUE (user_id, blocker_type, blocker_id, blocked_type, blocked_id)
        )
    """)

    op.execute("""
        CREATE TABLE subtasks (
            id      BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            task_id TEXT NOT NULL,
            text    TEXT NOT NULL,
            done    BOOLEAN NOT NULL DEFAULT FALSE,
            position INTEGER NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
        CREATE TABLE links (
            id          BIGSERIAL PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            parent_type TEXT NOT NULL,
            parent_id   TEXT NOT NULL,
            url         TEXT NOT NULL,
            label       TEXT,
            category    TEXT NOT NULL DEFAULT 'other',
            created_at  TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE context_entries (
            id         BIGSERIAL PRIMARY KEY,
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            subject    TEXT NOT NULL,
            body       TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, subject)
        )
    """)

    op.execute("""
        CREATE TABLE task_context (
            task_id          TEXT NOT NULL,
            user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            context_entry_id BIGINT NOT NULL REFERENCES context_entries(id) ON DELETE CASCADE,
            PRIMARY KEY (task_id, context_entry_id)
        )
    """)

    op.execute("""
        CREATE TABLE milestones (
            id               UUID PRIMARY KEY,
            user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            context_entry_id BIGINT REFERENCES context_entries(id) ON DELETE CASCADE,
            name             TEXT NOT NULL,
            description      TEXT,
            target_date      TEXT,
            status           TEXT NOT NULL DEFAULT 'pending',
            status_override  BOOLEAN NOT NULL DEFAULT FALSE,
            color            TEXT,
            created_at       TIMESTAMPTZ DEFAULT now(),
            updated_at       TIMESTAMPTZ DEFAULT now(),
            version          INTEGER NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
        CREATE TABLE milestone_tasks (
            milestone_id UUID NOT NULL REFERENCES milestones(id) ON DELETE CASCADE,
            task_id      TEXT NOT NULL,
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (milestone_id, task_id)
        )
    """)

    op.execute("""
        CREATE TABLE followup_state (
            id                  BIGSERIAL PRIMARY KEY,
            user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date                TEXT NOT NULL,
            anchor_id           TEXT NOT NULL,
            task_id             TEXT NOT NULL,
            sequence_started_at TIMESTAMPTZ NOT NULL,
            acknowledged_at     TIMESTAMPTZ,
            pre_ack_pings_sent  INTEGER DEFAULT 0,
            post_ack_pings_sent INTEGER DEFAULT 0,
            last_ping_at        TIMESTAMPTZ,
            completed           BOOLEAN DEFAULT FALSE,
            UNIQUE (user_id, date, task_id)
        )
    """)

    op.execute("""
        CREATE TABLE acknowledgements (
            plan_date       TEXT NOT NULL,
            anchor_id       TEXT NOT NULL,
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            acknowledged_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (plan_date, anchor_id, user_id)
        )
    """)

    op.execute("""
        CREATE TABLE check_ins (
            id             BIGSERIAL PRIMARY KEY,
            user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            plan_date      TEXT NOT NULL,
            anchor_id      TEXT NOT NULL,
            type           TEXT NOT NULL,
            timestamp      TEXT NOT NULL,
            accomplished   TEXT NOT NULL DEFAULT '',
            current_status TEXT NOT NULL DEFAULT ''
        )
    """)

    op.execute("""
        CREATE TABLE edit_history (
            id          BIGSERIAL PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            table_name  TEXT NOT NULL,
            operation   TEXT NOT NULL,
            record_id   TEXT NOT NULL,
            before_json JSONB,
            after_json  JSONB,
            created_at  TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE conversation_history (
            id      BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role    TEXT NOT NULL,
            body    TEXT NOT NULL,
            ts      TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE staging_mutations (
            id          TEXT NOT NULL,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_id  TEXT NOT NULL,
            type        TEXT NOT NULL,
            description TEXT NOT NULL,
            params_json JSONB NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (id, user_id)
        )
    """)

    op.execute("""
        CREATE TABLE orchestrator_conversation (
            id         BIGSERIAL PRIMARY KEY,
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            body       TEXT NOT NULL,
            round_num  INTEGER NOT NULL,
            ts         TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE invocation_log (
            id         BIGSERIAL PRIMARY KEY,
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_id TEXT NOT NULL,
            stage      TEXT NOT NULL,
            prompt     TEXT NOT NULL DEFAULT '',
            response   TEXT NOT NULL DEFAULT '',
            error      TEXT,
            ts         TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE state_monitor_log (
            id          BIGSERIAL PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            change_type TEXT NOT NULL,
            entity_id   TEXT NOT NULL DEFAULT '',
            score       INTEGER NOT NULL DEFAULT 1,
            consumed    BOOLEAN NOT NULL DEFAULT FALSE,
            ts          TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE beacon_state (
            user_id         UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            last_invoked_at TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE kanban_columns (
            id          UUID PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            position    INTEGER NOT NULL DEFAULT 0,
            color       TEXT,
            match_rules JSONB NOT NULL DEFAULT '{}',
            entry_rules JSONB NOT NULL DEFAULT '{}',
            created_by  TEXT
        )
    """)

    op.execute("""
        CREATE TABLE user_settings (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key     TEXT NOT NULL,
            value   TEXT NOT NULL,
            PRIMARY KEY (user_id, key)
        )
    """)

    op.execute("""
        CREATE TABLE context_nodes (
            id              UUID PRIMARY KEY,
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            parent_id       UUID REFERENCES context_nodes(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            node_type       TEXT NOT NULL DEFAULT 'context',
            description     TEXT,
            archived        BOOLEAN NOT NULL DEFAULT FALSE,
            target_date     TEXT,
            status          TEXT DEFAULT 'pending',
            status_override BOOLEAN NOT NULL DEFAULT FALSE,
            color           TEXT,
            created_at      TIMESTAMPTZ DEFAULT now(),
            updated_at      TIMESTAMPTZ DEFAULT now(),
            version         INTEGER NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
        CREATE TABLE node_sections (
            id            BIGSERIAL PRIMARY KEY,
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            node_id       UUID NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
            section_type  TEXT NOT NULL,
            name          TEXT NOT NULL DEFAULT 'main',
            body          TEXT NOT NULL DEFAULT '',
            updated_at    TIMESTAMPTZ DEFAULT now(),
            position      INTEGER NOT NULL DEFAULT 0,
            search_vector TSVECTOR,
            version       INTEGER NOT NULL DEFAULT 0,
            UNIQUE(node_id, section_type, name)
        )
    """)

    op.execute("""
        CREATE TABLE node_tasks (
            node_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (node_id, task_id)
        )
    """)

    op.execute("""
        CREATE TABLE sessions (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            chat_id       TEXT NOT NULL,
            state         TEXT NOT NULL DEFAULT 'active',
            turn_count    INTEGER NOT NULL DEFAULT 0,
            max_turns     INTEGER NOT NULL DEFAULT 10,
            summary       TEXT,
            created_at    TIMESTAMPTZ DEFAULT now(),
            last_activity TIMESTAMPTZ DEFAULT now()
        )
    """)

    # ── Cloud-only tables ─────────────────────────────────────────────────────

    op.execute("""
        CREATE TABLE api_keys (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key_hash    TEXT NOT NULL,
            key_prefix  TEXT NOT NULL,
            name        TEXT NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT now(),
            last_used_at TIMESTAMPTZ,
            revoked_at  TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE byok_keys (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider      TEXT NOT NULL,
            encrypted_key BYTEA NOT NULL,
            nonce         BYTEA NOT NULL,
            key_preview   TEXT NOT NULL,
            created_at    TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE llm_usage (
            id           BIGSERIAL PRIMARY KEY,
            user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at   TIMESTAMPTZ DEFAULT now(),
            provider     TEXT NOT NULL,
            model        TEXT NOT NULL,
            role         TEXT,
            input_tokens  INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cost_cents   INTEGER NOT NULL DEFAULT 0,
            key_source   TEXT,
            session_id   TEXT,
            request_id   UUID
        )
    """)

    op.execute("""
        CREATE TABLE subscriptions (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id              UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            stripe_customer_id   TEXT,
            stripe_sub_id        TEXT,
            plan                 TEXT NOT NULL DEFAULT 'free',
            status               TEXT NOT NULL DEFAULT 'active',
            allotment_cents      INTEGER NOT NULL DEFAULT 0,
            current_period_start TIMESTAMPTZ,
            current_period_end   TIMESTAMPTZ,
            created_at           TIMESTAMPTZ DEFAULT now()
        )
    """)

    # ── Bot-intelligence tables (forward-compat) ──────────────────────────────

    op.execute("""
        CREATE TABLE mutation_journal (
            id                BIGSERIAL PRIMARY KEY,
            user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_id        TEXT,
            parent_session_id TEXT,
            turn_number       INTEGER,
            source            TEXT NOT NULL,
            op_class          TEXT NOT NULL,
            checkpoint_label  TEXT,
            forward_op        JSONB NOT NULL,
            before_image      JSONB,
            after_image       JSONB,
            scope             JSONB,
            created_at        TIMESTAMPTZ DEFAULT now(),
            rolled_back_by    BIGINT REFERENCES mutation_journal(id)
        )
    """)

    op.execute("CREATE INDEX idx_journal_user_time ON mutation_journal(user_id, created_at DESC)")
    op.execute("CREATE INDEX idx_journal_session ON mutation_journal(session_id) WHERE session_id IS NOT NULL")

    op.execute("""
        CREATE TABLE session_activity_window (
            id          BIGSERIAL PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_id  TEXT NOT NULL,
            source      TEXT NOT NULL,
            op_class    TEXT NOT NULL,
            scope       JSONB NOT NULL,
            acquired_at TIMESTAMPTZ DEFAULT now(),
            expires_at  TIMESTAMPTZ NOT NULL,
            released_at TIMESTAMPTZ
        )
    """)

    op.execute("CREATE INDEX idx_activity_user_active ON session_activity_window(user_id, released_at) WHERE released_at IS NULL")

    # ── FTS trigger ───────────────────────────────────────────────────────────

    op.execute("""
        CREATE FUNCTION node_sections_search_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english',
                coalesce(NEW.name, '') || ' ' || coalesce(NEW.body, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER trig_node_sections_search
            BEFORE INSERT OR UPDATE ON node_sections
            FOR EACH ROW EXECUTE FUNCTION node_sections_search_trigger()
    """)

    # ── Indexes ───────────────────────────────────────────────────────────────

    op.execute("CREATE INDEX idx_tasks_user_date ON tasks(user_id, plan_date)")
    op.execute("CREATE UNIQUE INDEX idx_tasks_uuid ON tasks(uuid)")
    op.execute("CREATE UNIQUE INDEX idx_context_nodes_root ON context_nodes(user_id, name) WHERE parent_id IS NULL")
    op.execute("CREATE UNIQUE INDEX idx_context_nodes_sibling ON context_nodes(user_id, parent_id, name)")
    op.execute("CREATE INDEX idx_node_sections_search ON node_sections USING GIN(search_vector)")
    op.execute("CREATE INDEX idx_node_sections_node ON node_sections(node_id)")
    op.execute("CREATE INDEX idx_sessions_active ON sessions(user_id, chat_id, state) WHERE state IN ('active', 'waiting_user')")
    op.execute("CREATE INDEX idx_llm_usage_user_period ON llm_usage(user_id, created_at)")

    # ── Row-Level Security ────────────────────────────────────────────────────
    # All user-data tables use RLS. current_setting(..., true) returns NULL
    # (not error) when unset — policy evaluates to false, blocking all rows.
    # This is safe for migrations, admin queries, and Alembic runs.

    _rls_tables = [
        "anchors", "plans", "tasks", "task_dependencies", "dependencies",
        "subtasks", "links", "context_entries", "task_context", "milestones",
        "milestone_tasks", "followup_state", "acknowledgements", "check_ins",
        "edit_history", "conversation_history", "staging_mutations",
        "orchestrator_conversation", "invocation_log", "state_monitor_log",
        "beacon_state", "kanban_columns", "user_settings", "context_nodes",
        "node_sections", "node_tasks", "sessions", "api_keys", "byok_keys",
        "llm_usage", "subscriptions", "mutation_journal", "session_activity_window",
    ]

    for table in _rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_user_isolation ON {table}
                USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """)


def downgrade() -> None:
    tables = [
        "session_activity_window", "mutation_journal", "subscriptions",
        "llm_usage", "byok_keys", "api_keys", "sessions", "node_tasks",
        "node_sections", "context_nodes", "user_settings", "kanban_columns",
        "beacon_state", "state_monitor_log", "invocation_log",
        "orchestrator_conversation", "staging_mutations", "conversation_history",
        "edit_history", "check_ins", "acknowledgements", "followup_state",
        "milestone_tasks", "milestones", "task_context", "context_entries",
        "links", "subtasks", "dependencies", "task_dependencies", "tasks",
        "plans", "anchors", "telegram_link_codes", "telegram_connections",
        "invite_tokens", "oauth_connections", "users",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS node_sections_search_trigger() CASCADE")
