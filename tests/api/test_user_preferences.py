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


# ---------------------------------------------------------------------------
# notification_routing GET / PATCH
# ---------------------------------------------------------------------------

_VALID_ROUTING = {
    "anchor_ping": {
        "mode": "thread_by_key",
        "key_template": "anchor:{anchor_id}:{date}",
        "priority": "important",
        "external": ["telegram"],
    },
    "task_followup": {
        "mode": "thread_by_key",
        "key_template": "anchor:{anchor_id}:{date}",
        "priority": "important",
        "external": ["telegram"],
    },
    "beacon": {"mode": "bot_decides", "priority": "normal", "external": ["web"]},
    "meeting_event": {
        "mode": "thread_by_key",
        "key_template": "meeting:{request_id}",
        "priority": "important",
        "external": ["telegram", "web"],
    },
    "scheduling_update": {"mode": "fixed", "priority": "normal", "external": ["web"]},
}


@pytest.mark.asyncio
async def test_get_preferences_returns_notification_routing_defaults_when_unset(api_client, conn):
    """GET /api/user/preferences returns default routing when no prefs stored."""
    resp = await api_client.get("/api/user/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert "notification_routing" in data
    routing = data["notification_routing"]
    # All 5 default types present
    for key in ("anchor_ping", "task_followup", "beacon", "meeting_event", "scheduling_update"):
        assert key in routing


@pytest.mark.asyncio
async def test_patch_notification_routing_happy_path(api_client, conn):
    """PATCH with valid notification_routing stores and is reflected in GET."""
    resp = await api_client.patch(
        "/api/user/preferences", json={"notification_routing": _VALID_ROUTING}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    resp2 = await api_client.get("/api/user/preferences")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["notification_routing"]["anchor_ping"]["mode"] == "thread_by_key"
    assert data["notification_routing"]["beacon"]["priority"] == "normal"


@pytest.mark.asyncio
async def test_patch_notification_routing_rejects_unknown_type(api_client, conn):
    """PATCH rejects routing dicts containing unknown notification type keys."""
    bad_routing = {**_VALID_ROUTING, "unknown_type": {"mode": "fixed", "priority": "normal", "external": ["web"]}}
    resp = await api_client.patch(
        "/api/user/preferences", json={"notification_routing": bad_routing}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_notification_routing_rejects_invalid_mode(api_client, conn):
    """PATCH rejects routing entries with an invalid mode value."""
    bad_routing = {
        **_VALID_ROUTING,
        "beacon": {"mode": "send_everywhere", "priority": "normal", "external": ["web"]},
    }
    resp = await api_client.patch(
        "/api/user/preferences", json={"notification_routing": bad_routing}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_notification_routing_rejects_invalid_priority(api_client, conn):
    """PATCH rejects routing entries with an invalid priority value."""
    bad_routing = {
        **_VALID_ROUTING,
        "beacon": {"mode": "bot_decides", "priority": "critical", "external": ["web"]},
    }
    resp = await api_client.patch(
        "/api/user/preferences", json={"notification_routing": bad_routing}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_user_is_paid_raises_without_rls_context(conn):
    """get_user_is_paid raises RuntimeError when called on an unscoped connection,
    so a future caller that forgets to pass a user-scoped conn fails loudly."""
    from db.pg_queries import get_user_is_paid

    # Reset the RLS context that the conn fixture set, simulating an unscoped conn.
    await conn.execute("SELECT set_config('app.current_user_id', '', true)")
    with pytest.raises(RuntimeError, match="user-scoped connection"):
        await get_user_is_paid(conn)
