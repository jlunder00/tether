import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".tether-config"
DB_PATH = CONFIG_DIR / "tether.db"
AUTH_DB_PATH = CONFIG_DIR / "auth.db"
USERS_DB_DIR = CONFIG_DIR / "users"
JWT_SECRET = os.environ.get("TETHER_JWT_SECRET", "dev-secret-change-in-production")
