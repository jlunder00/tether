"""Add permission_grants table — per-conversation tool permission grants.

When a user approves a permission_request for a specific (target, kind), a grant
is stored here so the PermissionGate can skip the interactive flow on subsequent
calls within the same conversation.

Design:
  - Grants live as long as the conversation does; no explicit TTL.
  - expires_at is NULL by default; may be used for future time-bounded grants.
  - The (user_id, conversation_id, target, kind) tuple is the natural lookup key.
  - ON DELETE CASCADE from users ensures no orphan grants.

Security:
  - ENABLE ROW LEVEL SECURITY + FORCE ROW LEVEL SECURITY
  - Policy: USING (user_id = current_setting('app.current_user_id', true)::uuid)

Revision ID: k1l2m3n4o5p6
Revises: j1k2l3m4n5o6
Create Date: 2026-06-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "k1l2m3n4o5p6"
down_revision = "j1k2l3m4n5o6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "permission_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("granted_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # Index for the primary lookup: does a grant exist for this (user, conv, target, kind)?
    op.create_index(
        "ix_permission_grants_lookup",
        "permission_grants",
        ["user_id", "conversation_id", "target", "kind"],
    )

    # Foreign key back to users (cascade on delete)
    op.create_foreign_key(
        "fk_permission_grants_user_id",
        "permission_grants",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # RLS
    op.execute("ALTER TABLE permission_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE permission_grants FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY permission_grants_user_isolation ON permission_grants
        USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS permission_grants_user_isolation ON permission_grants")
    op.drop_index("ix_permission_grants_lookup", table_name="permission_grants")
    op.drop_constraint("fk_permission_grants_user_id", "permission_grants", type_="foreignkey")
    op.drop_table("permission_grants")
