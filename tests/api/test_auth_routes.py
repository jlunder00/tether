"""Tests for /auth/* routes — register, login, logout, me, invites."""
from __future__ import annotations

import os
import pytest
import asyncpg


# ---------------------------------------------------------------------------
# Cleanup fixture — remove any users created during auth tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def cleanup_auth_data(pool):
    yield
    c = await asyncpg.connect(dsn=os.environ.get("DATABASE_URL", ""))
    try:
        await c.execute("DELETE FROM users WHERE email LIKE '%@example.com'")
    except Exception:
        pass
    finally:
        await c.close()


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_first_user_no_invite_needed(auth_client):
    resp = await auth_client.post("/auth/register", json={
        "username": "admin",
        "email": "admin@example.com",
        "password": "secret123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["is_admin"] is True
    assert "tether_token" in resp.cookies


@pytest.mark.asyncio
async def test_register_second_user_requires_invite(auth_client):
    # Register first user (admin)
    await auth_client.post("/auth/register", json={
        "username": "admin",
        "email": "admin@example.com",
        "password": "secret123",
    })
    # Try to register second without invite
    resp = await auth_client.post("/auth/register", json={
        "username": "user2",
        "email": "user2@example.com",
        "password": "pass456",
    })
    assert resp.status_code == 400
    assert "invite" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_with_valid_invite(auth_client):
    # Register first user (admin) and get cookie
    reg_resp = await auth_client.post("/auth/register", json={
        "username": "admin",
        "email": "admin@example.com",
        "password": "secret123",
    })
    assert reg_resp.status_code == 200

    # Create invite as admin
    invite_resp = await auth_client.post("/auth/invite")
    assert invite_resp.status_code == 200
    token = invite_resp.json()["token"]

    # Register second user with invite
    resp = await auth_client.post("/auth/register", json={
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
async def test_login_with_username(auth_client):
    await auth_client.post("/auth/register", json={
        "username": "alice",
        "email": "alice@example.com",
        "password": "mypassword",
    })
    await auth_client.post("/auth/logout")
    resp = await auth_client.post("/auth/login", json={
        "login": "alice",
        "password": "mypassword",
    })
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"
    assert "tether_token" in resp.cookies


@pytest.mark.asyncio
async def test_login_with_email(auth_client):
    await auth_client.post("/auth/register", json={
        "username": "bob",
        "email": "bob@example.com",
        "password": "bobpass",
    })
    await auth_client.post("/auth/logout")
    resp = await auth_client.post("/auth/login", json={
        "login": "bob@example.com",
        "password": "bobpass",
    })
    assert resp.status_code == 200
    assert resp.json()["username"] == "bob"
    assert "tether_token" in resp.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(auth_client):
    await auth_client.post("/auth/register", json={
        "username": "carol",
        "email": "carol@example.com",
        "password": "correctpass",
    })
    resp = await auth_client.post("/auth/login", json={
        "login": "carol",
        "password": "wrongpass",
    })
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_logout_clears_cookie(auth_client):
    await auth_client.post("/auth/register", json={
        "username": "dave",
        "email": "dave@example.com",
        "password": "davepass",
    })
    assert "tether_token" in auth_client.cookies
    resp = await auth_client.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert "tether_token" in set_cookie_header


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_returns_user_info(auth_client):
    await auth_client.post("/auth/register", json={
        "username": "eve",
        "email": "eve@example.com",
        "password": "evepass",
    })
    resp = await auth_client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "eve"
    assert "user_id" in data
    assert "is_admin" in data


@pytest.mark.asyncio
async def test_me_unauthenticated(auth_client):
    resp = await auth_client.get("/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Invite tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_invite_admin_only(auth_client):
    # Register first user (admin)
    await auth_client.post("/auth/register", json={
        "username": "admin",
        "email": "admin@example.com",
        "password": "adminpass",
    })

    # Admin can create invite
    resp = await auth_client.post("/auth/invite")
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "expires_at" in data

    # Register a non-admin user via the invite
    invite_token = data["token"]
    await auth_client.post("/auth/logout")
    await auth_client.post("/auth/register", json={
        "username": "nonadmin",
        "email": "nonadmin@example.com",
        "password": "nonadminpass",
        "invite_token": invite_token,
    })

    # Non-admin trying to create invite should get 403
    resp = await auth_client.post("/auth/invite")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_invites(auth_client):
    await auth_client.post("/auth/register", json={
        "username": "admin",
        "email": "admin@example.com",
        "password": "adminpass",
    })

    await auth_client.post("/auth/invite")
    await auth_client.post("/auth/invite")

    resp = await auth_client.get("/auth/invites")
    assert resp.status_code == 200
    invites = resp.json()
    assert len(invites) == 2
    assert all("token" in i for i in invites)
