"""API config — thin consumer of config.loader.

All resolution logic (env vars, YAML files, placeholder expansion, secrets.json
shim) lives in config/loader.py. This module just names the values the API needs.
"""
import base64
import os
from pathlib import Path

from config.loader import config

# Re-export CONFIG_DIR so api/main.py can call cfg.CONFIG_DIR.mkdir()
CONFIG_DIR = Path(os.environ.get("TETHER_CONFIG_DIR", Path.home() / ".tether-config"))

JWT_SECRET: str = config.get("jwt.secret", default="dev-secret-change-in-production")

# CORS — restrict to explicit origins; wildcard + credentials is rejected by browsers
ALLOWED_ORIGINS: list[str] = config.get_list(
    "cors.allowed_origins",
    default=["http://localhost:5173", "http://localhost:8000"],
)

# Cookie security — set False for local HTTP development via TETHER_COOKIE_SECURE=false
COOKIE_SECURE: bool = config.get_bool("cookie.secure", default=True)

# OAuth — GitHub
GITHUB_CLIENT_ID: str = config.get("oauth.github.client_id", default="")
GITHUB_CLIENT_SECRET: str = config.get("oauth.github.client_secret", default="")
GITHUB_CALLBACK_URL: str = config.get(
    "oauth.github.callback_url",
    default="http://localhost:8000/auth/github/callback",
)

# OAuth — Google (login)
GOOGLE_CLIENT_ID: str = config.get("oauth.google.client_id", default="")
GOOGLE_CLIENT_SECRET: str = config.get("oauth.google.client_secret", default="")
GOOGLE_CALLBACK_URL: str = config.get(
    "oauth.google.callback_url",
    default="http://localhost:8000/auth/google/callback",
)

# OAuth — Google Calendar integration (separate callback path from login)
GOOGLE_INTEGRATION_CALLBACK_URL: str = config.get(
    "oauth.google.integration_callback_url",
    default="http://localhost:8000/api/integrations/google/callback",
)

# Credentials vault — Fernet encryption key for per-user credentials blobs.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
VAULT_KEY_B64: str = config.get("vault.key", default="")
# Parse to bytes when non-empty; None signals vault is not configured
VAULT_KEY: bytes | None = base64.b64decode(VAULT_KEY_B64) if VAULT_KEY_B64 else None
