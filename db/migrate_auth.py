#!/usr/bin/env python3
"""One-time migration: create auth.db, first user, move tether.db to per-user DB."""
from pathlib import Path
import shutil
import uuid
import yaml
from db.auth_schema import init_auth_db
from db.auth_queries import create_user, set_telegram_connection

CONFIG_DIR = Path.home() / ".tether-config"
OLD_DB = CONFIG_DIR / "tether.db"
AUTH_DB = CONFIG_DIR / "auth.db"
USERS_DIR = CONFIG_DIR / "users"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def migrate():
    if AUTH_DB.exists():
        print("auth.db already exists — skipping migration.")
        return

    USERS_DIR.mkdir(parents=True, exist_ok=True)
    init_auth_db(AUTH_DB)

    # Create first admin user
    user = create_user(AUTH_DB, username="admin", email="admin@tether.local",
                       password_hash=None, is_admin=True)
    user_id = user["id"]
    print(f"Created admin user: {user_id}")

    # Move existing tether.db to user's DB
    if OLD_DB.exists():
        dest = USERS_DIR / f"{user_id}.db"
        shutil.copy2(OLD_DB, dest)
        OLD_DB.rename(OLD_DB.with_suffix(".db.bak"))
        print(f"Moved tether.db → users/{user_id}.db (backup at tether.db.bak)")

    # Migrate telegram chat_id from config.yaml
    if CONFIG_FILE.exists():
        try:
            config = yaml.safe_load(CONFIG_FILE.read_text())
            chat_id = str(config.get("telegram", {}).get("chat_id", ""))
            if chat_id:
                set_telegram_connection(AUTH_DB, user_id, chat_id)
                print(f"Linked telegram chat_id {chat_id} to admin user")
        except Exception as e:
            print(f"Warning: could not migrate telegram config: {e}")

    print("Migration complete.")
    print(f"Set a password: run the server, then POST /auth/register with username=admin")


if __name__ == "__main__":
    migrate()
