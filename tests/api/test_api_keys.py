"""API route tests for /api/keys — create, list, revoke."""
from __future__ import annotations
import pytest

pytestmark = pytest.mark.asyncio


async def test_create_key_returns_raw_key(api_client):
    resp = await api_client.post("/api/keys", json={"name": "my-key"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["raw_key"].startswith("ttr_")
    assert "id" in data
    assert "key_hash" not in data


async def test_create_key_requires_auth(auth_client):
    resp = await auth_client.post("/api/keys", json={"name": "my-key"})
    assert resp.status_code == 401


async def test_list_keys_returns_user_keys(api_client):
    await api_client.post("/api/keys", json={"name": "key-one"})
    await api_client.post("/api/keys", json={"name": "key-two"})
    resp = await api_client.get("/api/keys")
    assert resp.status_code == 200
    keys = resp.json()
    names = [k["name"] for k in keys]
    assert "key-one" in names
    assert "key-two" in names
    for k in keys:
        assert "key_hash" not in k


async def test_list_keys_requires_auth(auth_client):
    resp = await auth_client.get("/api/keys")
    assert resp.status_code == 401


async def test_list_keys_excludes_other_user_keys(api_client, api_client_b):
    await api_client.post("/api/keys", json={"name": "user-a-key"})
    resp = await api_client_b.get("/api/keys")
    assert resp.status_code == 200
    names = [k["name"] for k in resp.json()]
    assert "user-a-key" not in names


async def test_revoke_key(api_client):
    create_resp = await api_client.post("/api/keys", json={"name": "to-revoke"})
    key_id = create_resp.json()["id"]
    resp = await api_client.delete(f"/api/keys/{key_id}")
    assert resp.status_code == 200
    # After revocation, key should show revoked_at in list
    list_resp = await api_client.get("/api/keys")
    match = next(k for k in list_resp.json() if k["id"] == key_id)
    assert match["revoked_at"] is not None


async def test_revoke_key_requires_auth(auth_client):
    resp = await auth_client.delete("/api/keys/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 401


async def test_revoke_key_wrong_owner_is_noop(api_client, api_client_b):
    """User B cannot revoke user A's key."""
    create_resp = await api_client.post("/api/keys", json={"name": "a-key"})
    key_id = create_resp.json()["id"]
    resp = await api_client_b.delete(f"/api/keys/{key_id}")
    # Should be 200 (no error) but key stays active
    assert resp.status_code == 200
    list_resp = await api_client.get("/api/keys")
    match = next((k for k in list_resp.json() if k["id"] == key_id), None)
    assert match is not None
    assert match["revoked_at"] is None


async def test_create_key_limit_enforced(api_client, conn):
    """A user cannot have more than 20 active API keys; the 21st returns 422."""
    # Create 20 keys
    for i in range(20):
        resp = await api_client.post("/api/keys", json={"name": f"limit-key-{i}"})
        assert resp.status_code == 201, f"Expected 201 on key {i}, got {resp.status_code}"

    # The 21st should be rejected with 422
    resp = await api_client.post("/api/keys", json={"name": "one-too-many"})
    assert resp.status_code == 422
