import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("TETHER_CONFIG_DIR", Path.home() / ".tether-config"))
SECRETS_FILE = CONFIG_DIR / "secrets.json"

# Load secrets from file at startup — env vars override for dev/CI
_secrets: dict = {}
if SECRETS_FILE.exists():
    _secrets = json.loads(SECRETS_FILE.read_text())


def _get(key: str, default: str = "") -> str:
    """Env var wins, then secrets file, then default."""
    return os.environ.get(key) or _secrets.get(key) or default


JWT_SECRET = _get("TETHER_JWT_SECRET", "dev-secret-change-in-production")

# OAuth — GitHub
GITHUB_CLIENT_ID = _get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = _get("GITHUB_CLIENT_SECRET")
GITHUB_CALLBACK_URL = _get("GITHUB_CALLBACK_URL", "http://localhost:8000/auth/github/callback")

# OAuth — Google (login)
GOOGLE_CLIENT_ID = _get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _get("GOOGLE_CLIENT_SECRET")
GOOGLE_CALLBACK_URL = _get("GOOGLE_CALLBACK_URL", "http://localhost:8000/auth/google/callback")

# OAuth — Google Calendar integration (separate callback path from login)
GOOGLE_INTEGRATION_CALLBACK_URL = _get(
    "GOOGLE_INTEGRATION_CALLBACK_URL",
    "http://localhost:8000/api/integrations/google/callback",
)
