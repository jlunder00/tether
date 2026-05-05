from __future__ import annotations
import pytest

from datetime import datetime, timedelta, timezone
from pathlib import Path
try:
    from db.auth_schema import init_auth_db
    from db.auth_queries import (
        create_user,
        get_user_by_id,
        get_user_by_email,
        get_user_by_username,
        get_user_count,
        create_oauth_connection,
        get_user_by_oauth,
        create_invite_token,
        use_invite_token,
        get_invite_tokens,
        set_telegram_connection,
        get_user_by_telegram_chat_id,
        store_link_code,
        verify_and_consume_link_code,
    )
except ImportError:
    pytestmark = pytest.mark.skip(reason="Skipping as Sqlite DB is deprecated and the required imports have been removed. Ensure Postgres equivalents are tested prior to removing these tests")

@pytest.fixture
def auth_db(tmp_path):
    path = tmp_path / "auth.db"
    init_auth_db(path)
    return path


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def test_create_and_get_user_by_id(auth_db):
    user = create_user(auth_db, "alice", "alice@example.com")
    assert user["username"] == "alice"
    assert user["email"] == "alice@example.com"
    assert user["password_hash"] is None
    assert user["is_admin"] == 0

    fetched = get_user_by_id(auth_db, user["id"])
    assert fetched is not None
    assert fetched["id"] == user["id"]


def test_get_user_by_email(auth_db):
    create_user(auth_db, "bob", "bob@example.com")
    user = get_user_by_email(auth_db, "bob@example.com")
    assert user is not None
    assert user["username"] == "bob"


def test_get_user_by_username(auth_db):
    create_user(auth_db, "carol", "carol@example.com")
    user = get_user_by_username(auth_db, "carol")
    assert user is not None
    assert user["email"] == "carol@example.com"


def test_get_user_not_found(auth_db):
    assert get_user_by_id(auth_db, "nonexistent") is None
    assert get_user_by_email(auth_db, "nobody@example.com") is None
    assert get_user_by_username(auth_db, "nobody") is None


def test_user_count(auth_db):
    assert get_user_count(auth_db) == 0
    create_user(auth_db, "u1", "u1@example.com")
    assert get_user_count(auth_db) == 1
    create_user(auth_db, "u2", "u2@example.com")
    assert get_user_count(auth_db) == 2


def test_create_admin_user(auth_db):
    user = create_user(auth_db, "admin", "admin@example.com", is_admin=True)
    assert user["is_admin"] == 1


def test_create_user_with_password_hash(auth_db):
    user = create_user(auth_db, "dave", "dave@example.com", password_hash="hashed!")
    assert user["password_hash"] == "hashed!"


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

def test_create_and_get_user_by_oauth(auth_db):
    user = create_user(auth_db, "eve", "eve@example.com")
    create_oauth_connection(auth_db, user["id"], "github", "gh-123", access_token="tok")
    found = get_user_by_oauth(auth_db, "github", "gh-123")
    assert found is not None
    assert found["id"] == user["id"]
    assert found["username"] == "eve"


def test_get_user_by_oauth_not_found(auth_db):
    assert get_user_by_oauth(auth_db, "github", "no-such-id") is None


def test_oauth_with_tokens(auth_db):
    user = create_user(auth_db, "frank", "frank@example.com")
    create_oauth_connection(
        auth_db, user["id"], "google", "ggl-456",
        access_token="at", refresh_token="rt",
    )
    found = get_user_by_oauth(auth_db, "google", "ggl-456")
    assert found["id"] == user["id"]


# ---------------------------------------------------------------------------
# Invite tokens
# ---------------------------------------------------------------------------

def _future(seconds=3600) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _past(seconds=3600) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


def test_create_and_use_invite_token(auth_db):
    creator = create_user(auth_db, "gina", "gina@example.com")
    redeemer = create_user(auth_db, "henry", "henry@example.com")

    token = create_invite_token(auth_db, creator["id"], _future())
    assert isinstance(token, str) and len(token) > 0

    result = use_invite_token(auth_db, token, redeemer["id"])
    assert result is True


def test_use_invite_token_already_used(auth_db):
    creator = create_user(auth_db, "ida", "ida@example.com")
    redeemer1 = create_user(auth_db, "jake", "jake@example.com")
    redeemer2 = create_user(auth_db, "kate", "kate@example.com")

    token = create_invite_token(auth_db, creator["id"], _future())
    assert use_invite_token(auth_db, token, redeemer1["id"]) is True
    assert use_invite_token(auth_db, token, redeemer2["id"]) is False


def test_use_invite_token_expired(auth_db):
    creator = create_user(auth_db, "leo", "leo@example.com")
    redeemer = create_user(auth_db, "mia", "mia@example.com")

    token = create_invite_token(auth_db, creator["id"], _past())
    assert use_invite_token(auth_db, token, redeemer["id"]) is False


def test_use_invite_token_nonexistent(auth_db):
    create_user(auth_db, "ned", "ned@example.com")
    assert use_invite_token(auth_db, "no-such-token", "some-id") is False


def test_get_invite_tokens(auth_db):
    creator = create_user(auth_db, "oli", "oli@example.com")
    t1 = create_invite_token(auth_db, creator["id"], _future())
    t2 = create_invite_token(auth_db, creator["id"], _future())
    tokens = get_invite_tokens(auth_db, creator["id"])
    token_values = {t["token"] for t in tokens}
    assert {t1, t2} == token_values


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def test_set_and_get_telegram_connection(auth_db):
    user = create_user(auth_db, "pat", "pat@example.com")
    set_telegram_connection(auth_db, user["id"], "chat-999")
    found = get_user_by_telegram_chat_id(auth_db, "chat-999")
    assert found is not None
    assert found["id"] == user["id"]
    assert found["username"] == "pat"


def test_telegram_connection_not_found(auth_db):
    assert get_user_by_telegram_chat_id(auth_db, "no-such-chat") is None


def test_set_telegram_connection_replace(auth_db):
    user = create_user(auth_db, "quinn", "quinn@example.com")
    set_telegram_connection(auth_db, user["id"], "chat-old")
    set_telegram_connection(auth_db, user["id"], "chat-new")
    assert get_user_by_telegram_chat_id(auth_db, "chat-new") is not None
    assert get_user_by_telegram_chat_id(auth_db, "chat-old") is None


# ---------------------------------------------------------------------------
# Telegram link codes
# ---------------------------------------------------------------------------

def test_store_and_verify_link_code(auth_db):
    store_link_code(auth_db, "123456", "chat-abc")
    result = verify_and_consume_link_code(auth_db, "123456")
    assert result == "chat-abc"


def test_verify_link_code_not_found(auth_db):
    result = verify_and_consume_link_code(auth_db, "000000")
    assert result is None


def test_verify_link_code_expired(auth_db):
    from unittest.mock import patch
    from datetime import datetime, timezone, timedelta
    # Insert a code with a created_at 6 minutes ago by manipulating the DB directly
    from db.auth_schema import get_auth_db
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    with get_auth_db(auth_db) as conn:
        conn.execute(
            "INSERT INTO telegram_link_codes (code, telegram_chat_id, created_at) VALUES (?, ?, ?)",
            ("999999", "chat-expired", old_ts),
        )
    result = verify_and_consume_link_code(auth_db, "999999")
    assert result is None


def test_verify_link_code_consumes(auth_db):
    store_link_code(auth_db, "654321", "chat-xyz")
    first = verify_and_consume_link_code(auth_db, "654321")
    assert first == "chat-xyz"
    second = verify_and_consume_link_code(auth_db, "654321")
    assert second is None
