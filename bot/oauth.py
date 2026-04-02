"""OAuth token management for Anthropic subscription billing.

Reads tokens written by `claude /login` at ~/.claude/.credentials.json.
Handles expiry detection, refresh, and write-back.
"""
import json
import logging
import os
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_DEFAULT_CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")


class TokenRefreshError(Exception):
    pass


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_at_ms: int


def read_oauth_tokens(credentials_path: str = _DEFAULT_CREDENTIALS_PATH) -> OAuthTokens | None:
    """Read OAuth tokens from the credentials file. Returns None on any error."""
    try:
        with open(credentials_path) as f:
            data = json.load(f)
        oauth = data.get("claudeAiOauth")
        if not oauth:
            return None
        return OAuthTokens(
            access_token=oauth["accessToken"],
            refresh_token=oauth["refreshToken"],
            expires_at_ms=oauth["expiresAt"],
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def is_token_valid(tokens: OAuthTokens, buffer_seconds: int = 300) -> bool:
    """Return True if the token won't expire within buffer_seconds."""
    expires_at_s = tokens.expires_at_ms / 1000
    return time.time() < expires_at_s - buffer_seconds


def refresh_tokens(tokens: OAuthTokens) -> OAuthTokens:
    """Exchange a refresh token for a new access token. Raises TokenRefreshError on failure."""
    resp = requests.post(
        _TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": OAUTH_CLIENT_ID,
        },
    )
    if not resp.ok:
        raise TokenRefreshError(f"Token refresh failed: {resp.status_code} {resp.text}")

    body = resp.json()
    expires_in_s = body.get("expires_in", 3600)
    return OAuthTokens(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", tokens.refresh_token),
        expires_at_ms=int((time.time() + expires_in_s) * 1000),
    )


def write_oauth_tokens(tokens: OAuthTokens, credentials_path: str = _DEFAULT_CREDENTIALS_PATH) -> None:
    """Write tokens back to the credentials file, preserving other top-level keys."""
    try:
        with open(credentials_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    data["claudeAiOauth"] = {
        "accessToken": tokens.access_token,
        "refreshToken": tokens.refresh_token,
        "expiresAt": tokens.expires_at_ms,
    }
    with open(credentials_path, "w") as f:
        json.dump(data, f)


def get_valid_token(credentials_path: str = _DEFAULT_CREDENTIALS_PATH) -> str | None:
    """Return a valid access token, refreshing if needed. Returns None if unavailable."""
    tokens = read_oauth_tokens(credentials_path)
    if tokens is None:
        return None

    if is_token_valid(tokens):
        return tokens.access_token

    # Token expired or near-expiry — attempt refresh
    try:
        new_tokens = refresh_tokens(tokens)
        write_oauth_tokens(new_tokens, credentials_path)
        return new_tokens.access_token
    except TokenRefreshError as e:
        logger.warning("OAuth token refresh failed: %s", e)
        return None
