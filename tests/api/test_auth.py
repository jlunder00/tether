"""Tests for api/auth.py — password hashing, JWT roundtrip, auth dependency."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from api.auth import (
    hash_password,
    verify_password,
    create_jwt,
    decode_jwt,
)
import jwt as pyjwt


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def test_hash_verify_password_roundtrip():
    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed) is True


def test_verify_password_wrong_password():
    hashed = hash_password("correct")
    assert verify_password("wrong", hashed) is False


# ---------------------------------------------------------------------------
# JWT roundtrip
# ---------------------------------------------------------------------------

def test_create_decode_jwt_roundtrip():
    token = create_jwt("user-abc", "alice", is_admin=False)
    payload = decode_jwt(token)
    assert payload["user_id"] == "user-abc"
    assert payload["username"] == "alice"
    assert payload["is_admin"] is False


def test_create_decode_jwt_admin():
    token = create_jwt("user-xyz", "admin", is_admin=True)
    payload = decode_jwt(token)
    assert payload["is_admin"] is True


def test_decode_expired_jwt_raises():
    import api.config as cfg
    from datetime import datetime, timedelta, timezone

    expired_payload = {
        "user_id": "user-123",
        "username": "test",
        "is_admin": False,
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    token = pyjwt.encode(expired_payload, cfg.JWT_SECRET, algorithm="HS256")
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_jwt(token)


def test_decode_invalid_jwt_raises():
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_jwt("not.a.valid.token")


# ---------------------------------------------------------------------------
# auth_dependency — unauthenticated request returns 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(auth_client):
    resp = await auth_client.get("/api/context")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_returns_401(auth_client):
    # Override the cookie on the auth_client (which has no cookie by default)
    resp = await auth_client.get(
        "/api/context",
        cookies={"tether_token": "bad.token.here"},
    )
    assert resp.status_code == 401
