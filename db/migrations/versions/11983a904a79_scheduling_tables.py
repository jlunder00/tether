"""scheduling_tables

Revision ID: 11983a904a79
Revises: 853542d7b568
Create Date: 2026-04-19 22:49:36.611423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11983a904a79'
down_revision: Union[str, Sequence[str], None] = '853542d7b568'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE connections (
            id           BIGSERIAL PRIMARY KEY,
            user_a       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            user_b       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status       TEXT NOT NULL DEFAULT 'pending',
            initiated_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            auto_schedule BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ DEFAULT now(),
            updated_at   TIMESTAMPTZ DEFAULT now(),
            UNIQUE(user_a, user_b),
            CHECK(user_a < user_b)
        )
    """)

    op.execute("""
        ALTER TABLE connections ENABLE ROW LEVEL SECURITY
    """)
    op.execute("""
        ALTER TABLE connections FORCE ROW LEVEL SECURITY
    """)
    op.execute("""
        CREATE POLICY connections_user_isolation ON connections
            USING (
                user_a = current_setting('app.current_user_id', true)::uuid
                OR user_b = current_setting('app.current_user_id', true)::uuid
            )
    """)

    op.execute("""
        CREATE TABLE meeting_requests (
            id               BIGSERIAL PRIMARY KEY,
            initiator_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            target_ids       UUID[] NOT NULL,
            duration_minutes INTEGER NOT NULL DEFAULT 30,
            context          TEXT,
            status           TEXT NOT NULL DEFAULT 'open',
            agreed_slot      TEXT,
            round            INTEGER NOT NULL DEFAULT 0,
            expires_at       TIMESTAMPTZ,
            created_at       TIMESTAMPTZ DEFAULT now(),
            updated_at       TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        ALTER TABLE meeting_requests ENABLE ROW LEVEL SECURITY
    """)
    op.execute("""
        ALTER TABLE meeting_requests FORCE ROW LEVEL SECURITY
    """)
    op.execute("""
        CREATE POLICY meeting_requests_user_isolation ON meeting_requests
            USING (
                initiator_id = current_setting('app.current_user_id', true)::uuid
                OR current_setting('app.current_user_id', true)::uuid = ANY(target_ids)
            )
    """)

    op.execute("""
        CREATE TABLE meeting_proposals (
            id          BIGSERIAL PRIMARY KEY,
            request_id  BIGINT NOT NULL REFERENCES meeting_requests(id) ON DELETE CASCADE,
            proposed_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            slots       TEXT[] NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            message     TEXT,
            created_at  TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        ALTER TABLE meeting_proposals ENABLE ROW LEVEL SECURITY
    """)
    op.execute("""
        ALTER TABLE meeting_proposals FORCE ROW LEVEL SECURITY
    """)
    op.execute("""
        CREATE POLICY meeting_proposals_user_isolation ON meeting_proposals
            USING (
                proposed_by = current_setting('app.current_user_id', true)::uuid
                OR request_id IN (
                    SELECT id FROM meeting_requests
                    WHERE initiator_id = current_setting('app.current_user_id', true)::uuid
                       OR current_setting('app.current_user_id', true)::uuid = ANY(target_ids)
                )
            )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS meeting_proposals")
    op.execute("DROP TABLE IF EXISTS meeting_requests")
    op.execute("DROP TABLE IF EXISTS connections")
