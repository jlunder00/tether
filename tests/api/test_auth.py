"""Tests for api/auth.py — password hashing, JWT roundtrip, auth dependency."""
from __future__ import annotations

import time
import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport

from api.auth import (
    hash_password,
    verify_password,
    create_jwt,
    decode_jwt,
)
from api.main import create_app
from db.schema import init_db
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

@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


@pytest.fixture
def app(db_path):
    return create_app(db_path=db_path)


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/context")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_returns_401(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": "bad.token.here"},
    ) as client:
        resp = await client.get("/api/context")
    assert resp.status_code == 401
