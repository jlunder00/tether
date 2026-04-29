"""Tests for GET/PATCH /api/user/preferences and is_paid in /auth/me."""
import pytest
from tests.api.conftest import TEST_USER_ID


@pytest.mark.asyncio
async def test_get_preferences_empty(api_client, conn):
    """GET /api/user/preferences returns None for both fields when no prefs set."""
    resp = await api_client.get("/api/user/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert data["theme"] is None
    assert data["mode"] is None


@pytest.mark.asyncio
async def test_patch_preferences_theme(api_client, conn):
    """PATCH /api/user/preferences with theme returns ok."""
    resp = await api_client.patch("/api/user/preferences", json={"theme": "dark"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_get_preferences_after_patch_theme(api_client, conn):
    """After patching theme, GET returns updated theme and mode still None."""
    await api_client.patch("/api/user/preferences", json={"theme": "dark"})
    resp = await api_client.get("/api/user/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert data["theme"] == "dark"
    assert data["mode"] is None


@pytest.mark.asyncio
async def test_patch_preferences_mode(api_client, conn):
    """Patching mode separately also works and is reflected in GET."""
    await api_client.patch("/api/user/preferences", json={"mode": "compact"})
    resp = await api_client.get("/api/user/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "compact"
    assert data["theme"] is None


@pytest.mark.asyncio
async def test_auth_me_includes_is_paid(api_client, conn):
    """GET /auth/me response includes is_paid field."""
    resp = await api_client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_paid" in data
