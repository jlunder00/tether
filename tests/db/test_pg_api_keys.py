"""Tests for api_keys DB queries — create, list, revoke, validate."""
from __future__ import annotations
import pytest

from tests.db.pg_conftest import auth_conn  # noqa: F401
from db.pg_queries.api_keys import (
    create_key,
    list_keys,
    revoke_key,
    validate_key,
)

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
pytestmark = pytest.mark.asyncio


async def test_create_key_returns_raw_key_and_record(auth_conn):
    raw_key, record = await create_key(auth_conn, TEST_USER_ID, "claude-code")
    assert raw_key.startswith("ttr_")
    assert len(raw_key) > 10
    assert record["user_id"] == TEST_USER_ID
    assert record["name"] == "claude-code"
    # hash must never appear in record surface
    assert "key_hash" not in record
    assert record.get("revoked_at") is None


async def test_list_keys_excludes_hash(auth_conn):
    await create_key(auth_conn, TEST_USER_ID, "key-one")
    await create_key(auth_conn, TEST_USER_ID, "key-two")
    keys = await list_keys(auth_conn, TEST_USER_ID)
    assert len(keys) >= 2
    for k in keys:
        assert "key_hash" not in k


async def test_revoke_key_sets_revoked_at(auth_conn):
    raw_key, record = await create_key(auth_conn, TEST_USER_ID, "to-revoke")
    await revoke_key(auth_conn, record["id"], TEST_USER_ID)
    keys = await list_keys(auth_conn, TEST_USER_ID)
    match = next(k for k in keys if k["id"] == record["id"])
    assert match["revoked_at"] is not None


async def test_validate_key_happy_path(auth_conn):
    raw_key, _ = await create_key(auth_conn, TEST_USER_ID, "valid")
    user_id = await validate_key(auth_conn, raw_key)
    assert user_id == TEST_USER_ID


async def test_validate_key_wrong_key_returns_none(auth_conn):
    result = await validate_key(auth_conn, "ttr_notarealkey")
    assert result is None


async def test_validate_key_revoked_returns_none(auth_conn):
    raw_key, record = await create_key(auth_conn, TEST_USER_ID, "revoked-key")
    await revoke_key(auth_conn, record["id"], TEST_USER_ID)
    result = await validate_key(auth_conn, raw_key)
    assert result is None


async def test_validate_key_updates_last_used(auth_conn):
    raw_key, record = await create_key(auth_conn, TEST_USER_ID, "used-key")
    # last_used_at should be None before first use
    rows = await auth_conn.fetch(
        "SELECT last_used_at FROM api_keys WHERE id = $1::uuid", record["id"]
    )
    assert rows[0]["last_used_at"] is None
    await validate_key(auth_conn, raw_key)
    rows = await auth_conn.fetch(
        "SELECT last_used_at FROM api_keys WHERE id = $1::uuid", record["id"]
    )
    assert rows[0]["last_used_at"] is not None


async def test_revoke_key_wrong_owner_does_nothing(auth_conn):
    """Revoke with a different user_id should not revoke the key."""
    other_user = "00000000-0000-0000-0000-000000000099"
    raw_key, record = await create_key(auth_conn, TEST_USER_ID, "owned-key")
    await revoke_key(auth_conn, record["id"], other_user)
    # key should still be valid
    result = await validate_key(auth_conn, raw_key)
    assert result == TEST_USER_ID
