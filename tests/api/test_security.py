"""Security tests — OAuth CSRF state, invite gating, notify auth, JWT secret check.

TDD: tests written first; all should fail until implementation is added.
"""
from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import asyncpg

# ---------------------------------------------------------------------------
# Cleanup fixture
# ---------------------------------------------------------------------------

async def _wipe_test_users() -> None:
    c = await asyncpg.connect(dsn=os.environ.get("DATABASE_URL", ""))
    try:
        await c.execute("DELETE FROM users WHERE email LIKE '%@sectest.example'")
    except Exception:
        pass
    finally:
        await c.close()


@pytest.fixture(autouse=True)
async def cleanup_security_test_users():
    await _wipe_test_users()
    yield
    await _wipe_test_users()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_state(payload: dict) -> str:
    """Generate a valid HMAC-signed OAuth state."""
    from api.oauth_state import make_signed_state
    return make_signed_state(payload)


def _make_expired_state(payload: dict) -> str:
    """Generate a signed state with expiry in the past."""
    import base64, hashlib, hmac, json
    import api.config as cfg

    data = {**payload, "exp": int(time.time()) - 1}  # already expired
    payload_str = json.dumps(data, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(cfg.JWT_SECRET.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload_str}|{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _mock_github_client(github_user_id: str = "gh-999", login: str = "gh-user"):
    """Return a mock httpx.AsyncClient that simulates GitHub OAuth."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "fake-gh-token"}

    user_resp = MagicMock()
    user_resp.json.return_value = {
        "id": github_user_id,
        "login": login,
        "email": f"{login}@sectest.example",
    }

    mock_client.post.return_value = token_resp
    mock_client.get.return_value = user_resp
    return mock_client


def _mock_google_client(google_user_id: str = "goog-999", email: str = "goog@sectest.example"):
    """Return a mock httpx.AsyncClient that simulates Google OAuth."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "fake-google-token"}

    user_resp = MagicMock()
    user_resp.json.return_value = {
        "id": google_user_id,
        "email": email,
    }

    mock_client.post.return_value = token_resp
    mock_client.get.return_value = user_resp
    return mock_client


# ---------------------------------------------------------------------------
# H-2: OAuth callbacks reject missing/invalid/expired state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_github_callback_rejects_missing_state(auth_client, monkeypatch):
    """GitHub callback with no state param returns 400."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_github_client()):
        resp = await auth_client.get(
            "/auth/github/callback",
            params={"code": "fake-code"},
            follow_redirects=False,
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_github_callback_rejects_invalid_state(auth_client, monkeypatch):
    """GitHub callback with a bad-signature state returns 400."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_github_client()):
        resp = await auth_client.get(
            "/auth/github/callback",
            params={"code": "fake-code", "state": "this.is.not.valid"},
            follow_redirects=False,
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_github_callback_rejects_expired_state(auth_client, monkeypatch):
    """GitHub callback with an expired state returns 400."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")

    expired_state = _make_expired_state({"mode": "login"})

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_github_client()):
        resp = await auth_client.get(
            "/auth/github/callback",
            params={"code": "fake-code", "state": expired_state},
            follow_redirects=False,
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_rejects_missing_state(auth_client, monkeypatch):
    """Google callback with no state param returns 400."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_google_client()):
        resp = await auth_client.get(
            "/auth/google/callback",
            params={"code": "fake-code"},
            follow_redirects=False,
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_rejects_expired_state(auth_client, monkeypatch):
    """Google callback with an expired state returns 400."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")

    expired_state = _make_expired_state({"mode": "login"})

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_google_client()):
        resp = await auth_client.get(
            "/auth/google/callback",
            params={"code": "fake-code", "state": expired_state},
            follow_redirects=False,
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# H-1: OAuth callbacks check invite token for new accounts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_github_callback_new_user_requires_invite(auth_client, monkeypatch):
    """GitHub callback with mode=login and no existing account returns 400."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")

    state = _make_valid_state({"mode": "login"})

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_github_client(
        github_user_id="gh-new-99", login="gh-newuser"
    )):
        resp = await auth_client.get(
            "/auth/github/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
    assert resp.status_code == 400
    assert "invite" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_google_callback_new_user_requires_invite(auth_client, monkeypatch):
    """Google callback with mode=login and no existing account returns 400."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")

    state = _make_valid_state({"mode": "login"})

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_google_client(
        google_user_id="goog-new-99", email="goog-new-99@sectest.example"
    )):
        resp = await auth_client.get(
            "/auth/google/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
    assert resp.status_code == 400
    assert "invite" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_github_callback_new_user_invalid_invite_rejected(auth_client, monkeypatch):
    """GitHub callback with an invalid invite token in state returns 400."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")

    state = _make_valid_state({"invite_token": "not-a-real-token"})

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_github_client(
        github_user_id="gh-bad-inv", login="gh-badinv"
    )):
        resp = await auth_client.get(
            "/auth/github/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_github_callback_new_user_valid_invite_creates_account(auth_client, pool, monkeypatch):
    """GitHub callback with a valid invite token creates an account and redirects."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")

    # Create admin + invite token via the auth API
    await auth_client.post("/auth/register", json={
        "username": "admin-sec",
        "email": "admin-sec@sectest.example",
        "password": "adminpass",
    })
    inv_resp = await auth_client.post("/auth/invite")
    assert inv_resp.status_code == 200
    invite_token = inv_resp.json()["token"]

    state = _make_valid_state({"invite_token": invite_token})

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_github_client(
        github_user_id="gh-invited-1", login="gh-inviteduser"
    )):
        resp = await auth_client.get(
            "/auth/github/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
    # Should redirect on success
    assert resp.status_code in (302, 307)


# ---------------------------------------------------------------------------
# H-1: Existing OAuth users can log in without invite
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_github_callback_existing_user_login_no_invite(auth_client, pool, monkeypatch):
    """GitHub callback for an existing OAuth user logs in without invite token."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")

    # First: register admin + create oauth_connection manually
    reg = await auth_client.post("/auth/register", json={
        "username": "existing-gh",
        "email": "existing-gh@sectest.example",
        "password": "pass",
    })
    assert reg.status_code == 200
    user_id = reg.json()["user_id"]

    # Insert oauth_connection for this user
    c = await asyncpg.connect(dsn=os.environ.get("DATABASE_URL", ""))
    try:
        import uuid
        await c.execute(
            "INSERT INTO oauth_connections (user_id, provider, provider_user_id) VALUES ($1, 'github', $2)",
            uuid.UUID(user_id), "gh-existing-42",
        )
    finally:
        await c.close()

    state = _make_valid_state({"mode": "login"})

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_github_client(
        github_user_id="gh-existing-42", login="existing-gh"
    )):
        resp = await auth_client.get(
            "/auth/github/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
    # Existing user: redirect to app
    assert resp.status_code in (302, 307)


@pytest.mark.asyncio
async def test_google_callback_existing_user_login_no_invite(auth_client, pool, monkeypatch):
    """Google callback for an existing OAuth user logs in without invite token."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")

    reg = await auth_client.post("/auth/register", json={
        "username": "existing-goog",
        "email": "existing-goog@sectest.example",
        "password": "pass",
    })
    assert reg.status_code == 200
    user_id = reg.json()["user_id"]

    c = await asyncpg.connect(dsn=os.environ.get("DATABASE_URL", ""))
    try:
        import uuid
        await c.execute(
            "INSERT INTO oauth_connections (user_id, provider, provider_user_id) VALUES ($1, 'google', $2)",
            uuid.UUID(user_id), "goog-existing-42",
        )
    finally:
        await c.close()

    state = _make_valid_state({"mode": "login"})

    with patch("api.routes.auth.httpx.AsyncClient", return_value=_mock_google_client(
        google_user_id="goog-existing-42", email="existing-goog@sectest.example"
    )):
        resp = await auth_client.get(
            "/auth/google/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
    assert resp.status_code in (302, 307)


# ---------------------------------------------------------------------------
# H-3: /api/notify requires auth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_unauthenticated_returns_401(auth_client):
    """POST /api/notify without a token returns 401."""
    resp = await auth_client.post("/api/notify")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# M-1: JWT secret startup check
# ---------------------------------------------------------------------------

def test_jwt_secret_check_raises_on_default():
    """_check_jwt_secret raises RuntimeError when given the default dev secret."""
    from api.main import _check_jwt_secret
    with pytest.raises(RuntimeError, match="TETHER_JWT_SECRET"):
        _check_jwt_secret("dev-secret-change-in-production")


def test_jwt_secret_check_passes_on_strong_secret():
    """_check_jwt_secret does not raise when given a non-default secret."""
    from api.main import _check_jwt_secret
    _check_jwt_secret("a-very-long-and-random-secret-value-1234567890")  # should not raise
