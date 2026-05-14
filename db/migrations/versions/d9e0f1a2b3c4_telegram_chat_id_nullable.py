"""Make telegram_connections.telegram_chat_id nullable

Phase 2 of the per-user Telegram migration introduces a new UX flow where
users register their BotFather token (POST /api/auth/telegram-bot) BEFORE
linking their Telegram chat. This requires inserting a row in
telegram_connections without a chat_id.

With telegram_chat_id NOT NULL (the initial schema), that insert fails.
This migration drops the NOT NULL constraint.

The UNIQUE constraint stays — in Postgres, NULL != NULL for unique indexes,
so multiple users with telegram_chat_id = NULL do not conflict. Once a user
links their chat (POST /api/auth/telegram-link), the column is populated.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop NOT NULL — UNIQUE stays (NULLs are distinct in Postgres unique indexes)
    op.execute(
        "ALTER TABLE telegram_connections "
        "ALTER COLUMN telegram_chat_id DROP NOT NULL"
    )


def downgrade() -> None:
    # Re-add NOT NULL only if no existing NULLs (safe for single-user environments)
    op.execute(
        "ALTER TABLE telegram_connections "
        "ALTER COLUMN telegram_chat_id SET NOT NULL"
    )
