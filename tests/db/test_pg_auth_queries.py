"""Tests for db/pg_auth_queries.py — user CRUD, OAuth, Telegram."""
import pytest
import uuid

from tests.db.pg_conftest import auth_conn, TEST_USER_ID  # noqa: F401
from db import pg_auth_queries as auth


@pytest.mark.asyncio
async def test_get_user_by_id(auth_conn):
    user = await auth.get_user_by_id(auth_conn, TEST_USER_ID)
    assert user is not None
    assert user["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_get_user_by_email(auth_conn):
    user = await auth.get_user_by_email(auth_conn, "test@example.com")
    assert user is not None
    assert str(user["id"]) == TEST_USER_ID


@pytest.mark.asyncio
async def test_create_and_get_user(auth_conn):
    new_id = str(uuid.uuid4())
    await auth.create_user(auth_conn, "newuser", "new@example.com", password_hash="hash", id=new_id)
    user = await auth.get_user_by_id(auth_conn, new_id)
    assert user["username"] == "newuser"


@pytest.mark.asyncio
async def test_oauth_connection(auth_conn):
    await auth.create_oauth_connection(
        auth_conn, TEST_USER_ID, "google", "google-uid-123",
        access_token="tok", refresh_token="ref"
    )
    user = await auth.get_user_by_oauth(auth_conn, "google", "google-uid-123")
    assert user is not None
    assert str(user["id"]) == TEST_USER_ID


@pytest.mark.asyncio
async def test_telegram_connection(auth_conn):
    await auth.set_telegram_connection(auth_conn, TEST_USER_ID, "chat-9999")
    user = await auth.get_user_by_telegram_chat_id(auth_conn, "chat-9999")
    assert user is not None
    assert str(user["id"]) == TEST_USER_ID


@pytest.mark.asyncio
async def test_link_code_flow(auth_conn):
    await auth.store_link_code(auth_conn, "ABC123", "chat-link-test")
    chat_id = await auth.verify_and_consume_link_code(auth_conn, "ABC123")
    assert chat_id == "chat-link-test"
    # Code consumed — second call returns None
    chat_id2 = await auth.verify_and_consume_link_code(auth_conn, "ABC123")
    assert chat_id2 is None
