import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".tether-config"
DB_PATH = CONFIG_DIR / "tether.db"
AUTH_DB_PATH = CONFIG_DIR / "auth.db"
USERS_DB_DIR = CONFIG_DIR / "users"
JWT_SECRET = os.environ.get("TETHER_JWT_SECRET", "dev-secret-change-in-production")

# OAuth — GitHub
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_CALLBACK_URL = os.environ.get("GITHUB_CALLBACK_URL", "http://localhost:8000/auth/github/callback")

# OAuth — Google
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_CALLBACK_URL = os.environ.get("GOOGLE_CALLBACK_URL", "http://localhost:8000/auth/google/callback")
