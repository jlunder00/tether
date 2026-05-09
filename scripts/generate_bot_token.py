#!/usr/bin/env python3
"""Generate a long-lived JWT for the bot WS listener.

The bot WS listener (tether_premium.bot.scheduling.events) connects to /ws
and authenticates using a token stored in the TETHER_API_BOT_TOKEN Fly secret.

Usage:
    # Inside a Fly.io machine (JWT secret already in env):
    python scripts/generate_bot_token.py

    # Locally (must supply the same JWT secret as the target app):
    TETHER_JWT_SECRET=<secret> python scripts/generate_bot_token.py

Flags:
    --bot-service   Generate an is_bot_service token (default, recommended).
                    Registers the WS connection with per-user delegation filtering.
    --admin         Generate an is_admin token (legacy, uses __bot__ channel).

Output: the token value to set as TETHER_API_BOT_TOKEN Fly secret.
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import timedelta
from api.auth import create_jwt

# Reserved bot UUID — must not collide with any real user.
BOT_USER_ID = "00000000-0000-0000-0000-000000000b07"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a long-lived bot JWT.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--bot-service",
        action="store_true",
        default=True,
        help="Generate is_bot_service=True token (default, recommended for meeting listener)",
    )
    group.add_argument(
        "--admin",
        action="store_true",
        default=False,
        help="Generate is_admin=True token (legacy __bot__ channel path)",
    )
    args = parser.parse_args()

    use_bot_service = not args.admin

    token = create_jwt(
        BOT_USER_ID,
        "bot",
        is_admin=args.admin,
        is_bot_service=use_bot_service,
        expires_in=timedelta(days=365),
    )

    token_type = "is_bot_service=True" if use_bot_service else "is_admin=True"
    print(f"Generated bot token ({token_type}, expires 365 days):\n")
    print(token)
    print()
    print("Set as Fly secret:")
    print(f"  flyctl secrets set TETHER_API_BOT_TOKEN={token} --app tether-prod")
    print(f"  flyctl secrets set TETHER_API_BOT_TOKEN={token} --app tether-dev")
    print()
    print("Note: tether-prod and tether-dev use different JWT secrets.")
    print("Run this script inside each app's Fly machine to get the correct token:")
    print("  flyctl ssh console --app tether-prod -C 'python /app/scripts/generate_bot_token.py'")
    print("  flyctl ssh console --app tether-dev -C 'python /app/scripts/generate_bot_token.py'")


if __name__ == "__main__":
    main()
