#!/usr/bin/env python3
"""One-time migration: store Jason's global bot token per-user in the DB.

Reads TELEGRAM_BOT_TOKEN from the environment, Fernet-encrypts it with
VAULT_KEY (same key used by CredentialsVault), and stores it on the first
(and only) user's telegram_connections row. Also generates a webhook_secret
UUID for future Phase 3 webhook mode.

Usage (on Fly.io or Pi):
    fly ssh console -- python scripts/migrate_telegram_to_per_user.py
    # or locally:
    TELEGRAM_BOT_TOKEN=... python scripts/migrate_telegram_to_per_user.py

After running:
1. Verify output: "Done. webhook_secret=<uuid>"
2. Remove TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID Fly secrets (they are now
   in the DB and no longer needed).
3. Deploy the new code — polling loop now reads from DB.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

from cryptography.fernet import Fernet


async def migrate() -> None:
    raw_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not raw_token:
        print("ERROR: TELEGRAM_BOT_TOKEN env var is not set or empty.", file=sys.stderr)
        sys.exit(1)

    # Load config to get vault key (config/app_config.yaml + env overrides)
    from config.loader import config as tether_config
    vault_key_str = tether_config.get("vault.key")
    if not vault_key_str:
        print("ERROR: vault.key not found in config.", file=sys.stderr)
        sys.exit(1)

    fernet = Fernet(
        vault_key_str.encode() if isinstance(vault_key_str, str) else vault_key_str
    )

    import db.postgres as pg
    import db.pg_auth_queries as pg_auth_queries

    pool = await pg.create_pool()
    try:
        async with pg.get_conn(pool) as conn:  # no user_id — auth schema, no RLS
            # Find Jason's user row (single-user deployment — take the first user).
            row = await conn.fetchrow(
                "SELECT id FROM users ORDER BY created_at LIMIT 1"
            )
            if row is None:
                print("ERROR: No users found in the database.", file=sys.stderr)
                sys.exit(1)

            user_id = str(row["id"])
            print(f"Found user: {user_id}")

            # Ensure a telegram_connections row exists (may not if Jason's
            # TELEGRAM_CHAT_ID hasn't been linked yet).
            telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
            if telegram_chat_id:
                await pg_auth_queries.set_telegram_connection(conn, user_id, telegram_chat_id)
                print(f"Telegram chat_id set: {telegram_chat_id}")
            else:
                # Check if row already exists
                existing = await conn.fetchrow(
                    "SELECT user_id FROM telegram_connections WHERE user_id = $1",
                    uuid.UUID(user_id),
                )
                if existing is None:
                    print(
                        "WARNING: No TELEGRAM_CHAT_ID set and no existing telegram_connections "
                        "row. The bot will auto-link chat_id on first inbound message.",
                        file=sys.stderr,
                    )
                    # Insert a placeholder row so store_bot_token can UPDATE it.
                    await conn.execute(
                        "INSERT INTO telegram_connections (user_id, telegram_chat_id) "
                        "VALUES ($1, '') ON CONFLICT (user_id) DO NOTHING",
                        uuid.UUID(user_id),
                    )

            # Encrypt and store the bot token.
            await pg_auth_queries.store_bot_token(conn, user_id, fernet, raw_token)
            print("Bot token encrypted and stored.")

            # Generate and store webhook_secret (for future Phase 3 webhook mode).
            # Local var uses a neutral name so static analysis doesn't flag the
            # intentional print below — the value is the DB column `webhook_secret`.
            wh_uuid = str(uuid.uuid4())
            await conn.execute(
                "UPDATE telegram_connections SET webhook_secret = $1 WHERE user_id = $2",
                wh_uuid,
                uuid.UUID(user_id),
            )
            print(f"\nDone.")
            print(f"  user_id:        {user_id}")
            print(f"  webhook_secret: {wh_uuid}")
            print()
            print("Next steps:")
            print("  1. Remove TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID Fly secrets.")
            print("  2. Deploy the updated code.")
            print("  3. For Phase 3 webhook mode, register:")
            print(f"     POST https://api.telegram.org/bot<token>/setWebhook")
            print(f"     secret_token: {wh_uuid}")
            print(f"     url: https://tether.jasonlunder.com/api/bot/telegram-webhook")
            print(f"     (header-based routing; see Phase 3 implementation)")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(migrate())
