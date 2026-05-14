"""telegram per-user bot tokens

Adds encrypted bot token and webhook secret columns to telegram_connections,
enabling each user to register their own BotFather bot token.

- bot_token_encrypted: Fernet-encrypted bytes of the raw BotFather token.
  NULL = user has not yet registered a personal bot.
- webhook_secret: UUID we generate at token-registration time; passed as the
  X-Telegram-Bot-Api-Secret-Token header when Telegram calls our webhook
  endpoint, allowing O(1) user lookup without iterating all connections.

Revision ID: c8d9e0f1a2b3
Revises: b2c3d4e5f6a7
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE telegram_connections "
        "ADD COLUMN IF NOT EXISTS bot_token_encrypted BYTEA"
    )
    op.execute(
        "ALTER TABLE telegram_connections "
        "ADD COLUMN IF NOT EXISTS webhook_secret TEXT"
    )
    # Partial unique index — only non-NULL secrets are indexed, avoiding
    # false conflicts for users who haven't registered a bot yet.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS telegram_connections_webhook_secret_idx "
        "ON telegram_connections (webhook_secret) "
        "WHERE webhook_secret IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS telegram_connections_webhook_secret_idx"
    )
    op.execute(
        "ALTER TABLE telegram_connections "
        "DROP COLUMN IF EXISTS webhook_secret"
    )
    op.execute(
        "ALTER TABLE telegram_connections "
        "DROP COLUMN IF EXISTS bot_token_encrypted"
    )
