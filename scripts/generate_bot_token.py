#!/usr/bin/env python3
"""Generate a long-lived admin JWT for the bot WS listener.

Usage: python scripts/generate_bot_token.py

Output: the token + the config.yaml snippet to paste.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import timedelta
from api.auth import create_jwt

# Reserved bot UUID — must not collide with any real user
BOT_USER_ID = "00000000-0000-0000-0000-000000000b07"

token = create_jwt(BOT_USER_ID, "bot", is_admin=True, expires_in=timedelta(days=365))
print(f"Add to ~/.tether-config/config.yaml:\n\napi:\n  bot_token: {token}\n")
