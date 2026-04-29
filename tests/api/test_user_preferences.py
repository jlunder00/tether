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
async def test_patch_empty_body_rejected(api_client, conn):
    """PATCH with no fields provided returns 400 (not a silent no-op success)."""
    resp = await api_client.patch("/api/user/preferences", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_overwrites_existing(api_client, conn):
    """PATCH overwrites an existing preference value (exercises ON CONFLICT DO UPDATE)."""
    await api_client.patch("/api/user/preferences", json={"theme": "dark"})
    await api_client.patch("/api/user/preferences", json={"theme": "light"})
    resp = await api_client.get("/api/user/preferences")
    assert resp.status_code == 200
    assert resp.json()["theme"] == "light"


@pytest.mark.asyncio
async def test_auth_me_includes_is_paid_no_subscription(api_client, conn):
    """GET /auth/me returns is_paid=False when the user has no subscription row."""
    resp = await api_client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_paid" in data
    assert isinstance(data["is_paid"], bool)
    assert data["is_paid"] is False


@pytest.mark.asyncio
async def test_auth_me_is_paid_false_for_free_plan(api_client, conn):
    """A subscription row with plan='free' yields is_paid=False."""
    await conn.execute(
        "INSERT INTO subscriptions (user_id, plan) VALUES ($1::uuid, 'free')",
        TEST_USER_ID,
    )
    resp = await api_client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["is_paid"] is False


@pytest.mark.asyncio
async def test_auth_me_is_paid_true_for_premium_plan(api_client, conn):
    """A subscription row with plan!='free' (e.g. 'premium') yields is_paid=True."""
    await conn.execute(
        "INSERT INTO subscriptions (user_id, plan) VALUES ($1::uuid, 'premium')",
        TEST_USER_ID,
    )
    resp = await api_client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["is_paid"] is True


@pytest.mark.asyncio
async def test_auth_me_is_paid_false_for_cancelled_premium(api_client, conn):
    """A premium subscription with status!='active' does not grant paid access."""
    await conn.execute(
        "INSERT INTO subscriptions (user_id, plan, status) VALUES ($1::uuid, 'premium', 'cancelled')",
        TEST_USER_ID,
    )
    resp = await api_client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["is_paid"] is False


@pytest.mark.asyncio
async def test_get_user_is_paid_raises_without_rls_context(conn):
    """get_user_is_paid raises RuntimeError when called on an unscoped connection,
    so a future caller that forgets to pass a user-scoped conn fails loudly."""
    from db.pg_queries import get_user_is_paid

    # Reset the RLS context that the conn fixture set, simulating an unscoped conn.
    await conn.execute("SELECT set_config('app.current_user_id', '', true)")
    with pytest.raises(RuntimeError, match="user-scoped connection"):
        await get_user_is_paid(conn)
