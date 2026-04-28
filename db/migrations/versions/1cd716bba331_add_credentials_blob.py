"""add credentials_blob to user_integrations

Stores Fernet-encrypted Anthropic OAuth credentials per user.

Revision ID: 1cd716bba331
Revises: f1a2b3c4d5e6
Create Date: 2026-04-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "1cd716bba331"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # credentials_blob: Fernet-encrypted JSON bytes for Anthropic OAuth credentials
    op.execute(
        "ALTER TABLE user_integrations ADD COLUMN IF NOT EXISTS credentials_blob BYTEA NULL"
    )
    op.execute(
        "COMMENT ON COLUMN user_integrations.credentials_blob IS "
        "'Fernet-encrypted JSON credentials blob for provider OAuth tokens (e.g. Anthropic)'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_integrations DROP COLUMN IF EXISTS credentials_blob"
    )
