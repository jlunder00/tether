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


# ---------------------------------------------------------------------------
# auth_dependency — Bearer token fallback (unit tests, no DB required)
#
# These tests call auth_dependency directly with a mock Request rather than
# going through an HTTP client. This avoids needing a real Postgres pool while
# still verifying the exact auth logic.
# ---------------------------------------------------------------------------

TEST_BEARER_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_RAW_KEY = "ttr_testkey1234567890abcdefghijklmnopqrstuv"


def _make_request(*, cookie_token: str | None = None, auth_header: str | None = None):
    """Build a minimal mock Request for auth_dependency testing."""
    from unittest.mock import MagicMock

    request = MagicMock()
    request.cookies = {"tether_token": cookie_token} if cookie_token else {}
    request.headers = {"Authorization": auth_header} if auth_header else {}
    request.app.state.pool = MagicMock()  # never actually called when _validate_bearer_key is mocked
    return request


@pytest.mark.asyncio
async def test_bearer_valid_key_authenticates(monkeypatch):
    """Valid ttr_ Bearer key succeeds; user_id and is_admin are set correctly."""
    from unittest.mock import AsyncMock
    import api.auth as auth_mod
    from fastapi import HTTPException

    monkeypatch.setattr(auth_mod, "_validate_bearer_key", AsyncMock(return_value=TEST_BEARER_USER_ID))

    request = _make_request(auth_header=f"Bearer {TEST_RAW_KEY}")
    result = await auth_mod.auth_dependency(request)

    assert result["user_id"] == TEST_BEARER_USER_ID
    assert result["is_admin"] is False
    assert request.state.user_id == TEST_BEARER_USER_ID
    assert request.state.is_admin is False
    assert request.state.username is None


@pytest.mark.asyncio
async def test_bearer_invalid_key_returns_401(monkeypatch):
    """Invalid ttr_ Bearer key (validate returns None) → 401."""
    from unittest.mock import AsyncMock
    import api.auth as auth_mod
    from fastapi import HTTPException

    monkeypatch.setattr(auth_mod, "_validate_bearer_key", AsyncMock(return_value=None))

    request = _make_request(auth_header=f"Bearer {TEST_RAW_KEY}")
    with pytest.raises(HTTPException) as exc_info:
        await auth_mod.auth_dependency(request)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_bearer_non_ttr_prefix_ignored(monkeypatch):
    """Bearer token without ttr_ prefix falls through to cookie path → 401 (no cookie)."""
    import api.auth as auth_mod
    from fastapi import HTTPException

    request = _make_request(auth_header="Bearer some_other_token")
    with pytest.raises(HTTPException) as exc_info:
        await auth_mod.auth_dependency(request)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_cookie_wins_when_both_present(monkeypatch):
    """Valid cookie takes precedence; _validate_bearer_key is never called."""
    from unittest.mock import AsyncMock
    import api.auth as auth_mod

    mock_validate = AsyncMock(return_value=TEST_BEARER_USER_ID)
    monkeypatch.setattr(auth_mod, "_validate_bearer_key", mock_validate)

    token = create_jwt(TEST_BEARER_USER_ID, "testuser", is_admin=False)
    request = _make_request(cookie_token=token, auth_header=f"Bearer {TEST_RAW_KEY}")
    result = await auth_mod.auth_dependency(request)

    assert result["user_id"] == TEST_BEARER_USER_ID
    mock_validate.assert_not_called()


@pytest.mark.asyncio
async def test_neither_cookie_nor_bearer_returns_401():
    """No cookie, no Bearer → 401."""
    import api.auth as auth_mod
    from fastapi import HTTPException

    request = _make_request()
    with pytest.raises(HTTPException) as exc_info:
        await auth_mod.auth_dependency(request)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_cookie_auth_regression_passes():
    """Existing cookie auth still works — no regression."""
    import api.auth as auth_mod

    token = create_jwt("cookie-user-id", "cookieuser", is_admin=False)
    request = _make_request(cookie_token=token)
    result = await auth_mod.auth_dependency(request)

    assert result["user_id"] == "cookie-user-id"
    assert result["username"] == "cookieuser"
    assert result["is_admin"] is False
