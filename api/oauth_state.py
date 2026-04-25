"""HMAC-signed OAuth state helpers.

Provides make_signed_state / verify_signed_state for passing structured data
(invite tokens, login mode) through the OAuth redirect roundtrip without
relying on session cookies.

Format: base64url( JSON_payload + "|" + HMAC-SHA256-hex )
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

import api.config as cfg

_STATE_TTL_SECONDS = 600  # 10 minutes — long enough for a slow consent screen


def make_signed_state(payload: dict) -> str:
    """Sign *payload* with HMAC-SHA256 and return a base64url-encoded state string.

    An ``exp`` key is added to the payload automatically — callers should not
    include their own ``exp``.
    """
    data = {**payload, "exp": int(datetime.now(timezone.utc).timestamp()) + _STATE_TTL_SECONDS}
    payload_str = json.dumps(data, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(
        cfg.JWT_SECRET.encode(), payload_str.encode(), hashlib.sha256
    ).hexdigest()
    raw = f"{payload_str}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_signed_state(state: str) -> dict:
    """Verify signature and expiry of *state*; return the payload dict.

    Raises:
        ValueError: if the state is malformed, has an invalid signature, or is expired.
    """
    try:
        # Pad to a multiple of 4 for urlsafe_b64decode
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        payload_str, sig = raw.rsplit("|", 1)
        expected = hmac.new(
            cfg.JWT_SECRET.encode(), payload_str.encode(), hashlib.sha256
        ).hexdigest()
    except Exception as exc:
        raise ValueError("Malformed OAuth state") from exc

    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid OAuth state signature")

    data = json.loads(payload_str)
    if int(datetime.now(timezone.utc).timestamp()) > data.get("exp", 0):
        raise ValueError("OAuth state expired")

    return data
