"""Tests for /auth/* routes — register, login, logout, me, invites."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from pathlib import Path

from db.auth_schema import init_auth_db
from db.schema import init_db
from api.main import create_app
import api.config as cfg
import api.auth as auth_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_db_path(tmp_path):
    path = tmp_path / "auth.db"
    init_auth_db(path)
    return path


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


@pytest.fixture
def app(db_path, auth_db_path, tmp_path, monkeypatch):
    """Create app with patched AUTH_DB_PATH and USERS_DB_DIR pointing to tmp dirs."""
    monkeypatch.setattr(cfg, "AUTH_DB_PATH", auth_db_path)
    users_dir = tmp_path / "users"
    users_dir.mkdir()
    monkeypatch.setattr(cfg, "USERS_DB_DIR", users_dir)
    # Patch get_user_db_path to use the same tmp users_dir
    original_fn = auth_module.get_user_db_path

    def _patched_get_user_db_path(user_id: str) -> Path:
        return users_dir / f"{user_id}.db"

    monkeypatch.setattr(auth_module, "get_user_db_path", _patched_get_user_db_path)
    # Also patch in the routes module which imports get_user_db_path at function call time
    import api.routes.auth as auth_routes
    monkeypatch.setattr(auth_routes, "get_user_db_path", _patched_get_user_db_path)
    return create_app(db_path=db_path)


def make_client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_first_user_no_invite_needed(app):
    async with make_client(app) as client:
        resp = await client.post("/auth/register", json={
            "username": "admin",
            "email": "admin@example.com",
            "password": "secret123",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["is_admin"] is True
    # Cookie should be set
    assert "tether_token" in resp.cookies


@pytest.mark.asyncio
async def test_register_second_user_requires_invite(app):
    async with make_client(app) as client:
        # Register first user (admin)
        await client.post("/auth/register", json={
            "username": "admin",
            "email": "admin@example.com",
            "password": "secret123",
        })
        # Try to register second without invite
        resp = await client.post("/auth/register", json={
            "username": "user2",
            "email": "user2@example.com",
            "password": "pass456",
        })
    assert resp.status_code == 400
    assert "invite" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_with_valid_invite(app):
    async with make_client(app) as client:
        # Register first user (admin) and get cookie
        reg_resp = await client.post("/auth/register", json={
            "username": "admin",
            "email": "admin@example.com",
            "password": "secret123",
        })
        assert reg_resp.status_code == 200

        # Create invite as admin
        invite_resp = await client.post("/auth/invite")
        assert invite_resp.status_code == 200
        token = invite_resp.json()["token"]

        # Register second user with invite
        resp = await client.post("/auth/register", json={
            "username": "user2",
            "email": "user2@example.com",
            "password": "pass456",
            "invite_token": token,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "user2"
    assert data["is_admin"] is False


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_with_username(app):
    async with make_client(app) as client:
        await client.post("/auth/register", json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "mypassword",
        })
        # Log out so we can test fresh login
        await client.post("/auth/logout")
        resp = await client.post("/auth/login", json={
            "login": "alice",
            "password": "mypassword",
        })
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"
    assert "tether_token" in resp.cookies


@pytest.mark.asyncio
async def test_login_with_email(app):
    async with make_client(app) as client:
        await client.post("/auth/register", json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "bobpass",
        })
        await client.post("/auth/logout")
        resp = await client.post("/auth/login", json={
            "login": "bob@example.com",
            "password": "bobpass",
        })
    assert resp.status_code == 200
    assert resp.json()["username"] == "bob"
    assert "tether_token" in resp.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(app):
    async with make_client(app) as client:
        await client.post("/auth/register", json={
            "username": "carol",
            "email": "carol@example.com",
            "password": "correctpass",
        })
        resp = await client.post("/auth/login", json={
            "login": "carol",
            "password": "wrongpass",
        })
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logout_clears_cookie(app):
    async with make_client(app) as client:
        await client.post("/auth/register", json={
            "username": "dave",
            "email": "dave@example.com",
            "password": "davepass",
        })
        # Verify cookie is set after register
        assert "tether_token" in client.cookies
        resp = await client.post("/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # httpx AsyncClient removes cookies when server sets Max-Age=0 / delete
        # The response should have a Set-Cookie that deletes it
        set_cookie_header = resp.headers.get("set-cookie", "")
        assert "tether_token" in set_cookie_header


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_returns_user_info(app):
    async with make_client(app) as client:
        await client.post("/auth/register", json={
            "username": "eve",
            "email": "eve@example.com",
            "password": "evepass",
        })
        resp = await client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "eve"
    assert "user_id" in data
    assert "is_admin" in data


@pytest.mark.asyncio
async def test_me_unauthenticated(app):
    async with make_client(app) as client:
        resp = await client.get("/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Invite tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_invite_admin_only(app):
    async with make_client(app) as client:
        # Register first user (admin)
        await client.post("/auth/register", json={
            "username": "admin",
            "email": "admin@example.com",
            "password": "adminpass",
        })

        # Admin can create invite
        resp = await client.post("/auth/invite")
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert "expires_at" in data

        # Register a non-admin user via the invite
        invite_token = data["token"]
        await client.post("/auth/logout")
        await client.post("/auth/register", json={
            "username": "nonadmin",
            "email": "nonadmin@example.com",
            "password": "nonadminpass",
            "invite_token": invite_token,
        })

        # Non-admin trying to create invite should get 403
        resp = await client.post("/auth/invite")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_invites(app):
    async with make_client(app) as client:
        await client.post("/auth/register", json={
            "username": "admin",
            "email": "admin@example.com",
            "password": "adminpass",
        })

        # Create a couple of invites
        await client.post("/auth/invite")
        await client.post("/auth/invite")

        resp = await client.get("/auth/invites")
        assert resp.status_code == 200
        invites = resp.json()
        assert len(invites) == 2
        assert all("token" in i for i in invites)
