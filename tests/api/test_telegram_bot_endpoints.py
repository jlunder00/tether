"""Integration tests for POST/DELETE/GET /api/auth/telegram-bot endpoints.

TDD: tests written before implementation, confirmed to fail for the right reason.

Schema dependency: these tests require telegram_connections.telegram_chat_id
to be nullable (migration d9e0f1a2b3c4_telegram_chat_id_nullable.py). If the
column is NOT NULL, the upsert tests will fail at the DB layer.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient, ASGITransport

from api.auth import create_jwt
from db.postgres import register_jsonb_codec
from tests.api.conftest import TEST_USER_ID, TEST_USERNAME

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SAMPLE_GET_ME_RESPONSE = {
    "ok": True,
    "result": {
        "id": 123456789,
        "is_bot": True,
        "first_name": "Test Bot",
        "username": "testbot",
    },
}

SAMPLE_BOT_TOKEN = "1234567890:ABCDefghijklMNOpqrstuvwxyz"


def _make_mock_httpx_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Build a mock httpx Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    return mock_resp


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — API tests skipped")
    return url


async def _ensure_test_user(url: str) -> None:
    c = await asyncpg.connect(dsn=url)
    try:
        await c.execute(
            """
            INSERT INTO users (id, username, email, password_hash, is_admin)
            VALUES ($1::uuid, $2, 'test@example.com', 'x', false)
            ON CONFLICT (id) DO NOTHING
            """,
            TEST_USER_ID,
            TEST_USERNAME,
        )
    finally:
        await c.close()


async def _cleanup_telegram_connection(url: str) -> None:
    """Remove any telegram_connections row for the test user between tests."""
    c = await asyncpg.connect(dsn=url)
    try:
        await c.execute(
            "DELETE FROM telegram_connections WHERE user_id = $1::uuid",
            TEST_USER_ID,
        )
    finally:
        await c.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def pool():
    url = _db_url()
    p = await asyncpg.create_pool(dsn=url, init=register_jsonb_codec)
    yield p
    await p.close()


@pytest.fixture
async def telegram_bot_client(pool):
    """AsyncClient pre-configured with auth cookie + vault for telegram-bot endpoints.

    Yields (client, fernet) so tests can verify encrypted storage.
    """
    from api.main import create_app
    from api.credentials_vault import CredentialsVault

    url = _db_url()
    await _ensure_test_user(url)
    await _cleanup_telegram_connection(url)

    fernet_key = Fernet.generate_key()
    app = create_app()
    app.state.pool = pool
    app.state.vault = CredentialsVault(pool, fernet_key)
    fernet = Fernet(fernet_key)

    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client, fernet

    await _cleanup_telegram_connection(url)


@pytest.fixture
async def telegram_bot_client_with_existing_connection(pool):
    """Client where the test user already has a telegram_connections row
    (simulates a user who previously linked their Telegram chat)."""
    from api.main import create_app
    from api.credentials_vault import CredentialsVault

    url = _db_url()
    await _ensure_test_user(url)
    await _cleanup_telegram_connection(url)

    # Insert an existing telegram_connections row with a known chat_id
    c = await asyncpg.connect(dsn=url)
    try:
        await c.execute(
            """
            INSERT INTO telegram_connections (user_id, telegram_chat_id)
            VALUES ($1::uuid, $2)
            ON CONFLICT (user_id) DO NOTHING
            """,
            TEST_USER_ID,
            "existing_chat_id_123",
        )
    finally:
        await c.close()

    fernet_key = Fernet.generate_key()
    app = create_app()
    app.state.pool = pool
    app.state.vault = CredentialsVault(pool, fernet_key)
    fernet = Fernet(fernet_key)

    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client, fernet

    await _cleanup_telegram_connection(url)


# ---------------------------------------------------------------------------
# POST /api/auth/telegram-bot — invalid token → 400
# ---------------------------------------------------------------------------


async def test_post_telegram_bot_invalid_token_ok_false(telegram_bot_client):
    """Telegram returns ok:false → 400 with error message."""
    client, _ = telegram_bot_client

    mock_resp = _make_mock_httpx_response(
        {"ok": False, "error_code": 401, "description": "Unauthorized"}
    )
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        resp = await client.post(
            "/auth/telegram-bot",
            json={"token": "bad-token"},
        )

    assert resp.status_code == 400
    data = resp.json()
    assert "invalid" in data["detail"].lower() or "unauthorized" in data["detail"].lower()


async def test_post_telegram_bot_http_error_returns_400(telegram_bot_client):
    """Telegram API returns HTTP non-200 → 400."""
    client, _ = telegram_bot_client

    mock_resp = _make_mock_httpx_response({}, status_code=404)
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        resp = await client.post(
            "/auth/telegram-bot",
            json={"token": "bad-token"},
        )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/auth/telegram-bot — valid token → stores + returns bot_username
# ---------------------------------------------------------------------------


async def test_post_telegram_bot_valid_token_stores_and_returns(
    telegram_bot_client, pool
):
    """Valid token: encrypts + stores in telegram_connections, returns bot_username."""
    client, fernet = telegram_bot_client

    mock_resp = _make_mock_httpx_response(SAMPLE_GET_ME_RESPONSE)
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        resp = await client.post(
            "/auth/telegram-bot",
            json={"token": SAMPLE_BOT_TOKEN},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["bot_username"] == "@testbot"

    # Verify the token was encrypted and stored
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT bot_token_encrypted, webhook_secret FROM telegram_connections "
            "WHERE user_id = $1::uuid",
            TEST_USER_ID,
        )
    assert row is not None
    assert row["bot_token_encrypted"] is not None
    assert row["webhook_secret"] is not None
    # Decrypt and verify
    decrypted = fernet.decrypt(bytes(row["bot_token_encrypted"])).decode()
    assert decrypted == SAMPLE_BOT_TOKEN
    # webhook_secret is a UUID
    uuid.UUID(row["webhook_secret"])  # raises if not valid UUID


async def test_post_telegram_bot_upserts_when_connection_exists(
    telegram_bot_client_with_existing_connection, pool
):
    """POST with existing telegram_connections row (has chat_id) updates token columns."""
    client, fernet = telegram_bot_client_with_existing_connection

    mock_resp = _make_mock_httpx_response(SAMPLE_GET_ME_RESPONSE)
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        resp = await client.post(
            "/auth/telegram-bot",
            json={"token": SAMPLE_BOT_TOKEN},
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # The existing chat_id should be preserved
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT telegram_chat_id, bot_token_encrypted FROM telegram_connections "
            "WHERE user_id = $1::uuid",
            TEST_USER_ID,
        )
    assert row is not None
    assert row["telegram_chat_id"] == "existing_chat_id_123"  # preserved
    assert row["bot_token_encrypted"] is not None  # newly added


# ---------------------------------------------------------------------------
# POST /api/auth/telegram-bot — webhook_setup integration
# ---------------------------------------------------------------------------


async def test_post_telegram_bot_webhook_setup_called_when_url_set(
    telegram_bot_client, monkeypatch
):
    """When TELEGRAM_WEBHOOK_URL is set and webhook_setup is importable,
    register_webhook is called."""
    client, _ = telegram_bot_client
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com")

    register_called: list[tuple] = []

    async def mock_register(bot_token: str, public_url: str, webhook_secret: str) -> None:
        register_called.append((bot_token, public_url, webhook_secret))

    mock_module = MagicMock()
    mock_module.register_webhook = mock_register

    mock_resp = _make_mock_httpx_response(SAMPLE_GET_ME_RESPONSE)
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        with patch.dict("sys.modules", {"bot.webhook_setup": mock_module}):
            resp = await client.post(
                "/auth/telegram-bot",
                json={"token": SAMPLE_BOT_TOKEN},
            )

    assert resp.status_code == 200
    assert len(register_called) == 1
    assert register_called[0][0] == SAMPLE_BOT_TOKEN
    assert register_called[0][1] == "https://example.com"


async def test_post_telegram_bot_webhook_setup_import_error_still_succeeds(
    telegram_bot_client, monkeypatch
):
    """When TELEGRAM_WEBHOOK_URL is set but webhook_setup is not importable,
    the endpoint still succeeds (ImportError is swallowed)."""
    client, _ = telegram_bot_client
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com")

    mock_resp = _make_mock_httpx_response(SAMPLE_GET_ME_RESPONSE)
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        # Force ImportError for the webhook_setup module
        with patch.dict("sys.modules", {"bot.webhook_setup": None}):
            resp = await client.post(
                "/auth/telegram-bot",
                json={"token": SAMPLE_BOT_TOKEN},
            )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# DELETE /api/auth/telegram-bot — clears token + webhook secret
# ---------------------------------------------------------------------------


async def test_delete_telegram_bot_clears_columns(telegram_bot_client_with_existing_connection, pool):
    """DELETE clears bot_token_encrypted and webhook_secret."""
    client, fernet = telegram_bot_client_with_existing_connection

    # First set a bot token
    mock_resp = _make_mock_httpx_response(SAMPLE_GET_ME_RESPONSE)
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        post_resp = await client.post(
            "/auth/telegram-bot",
            json={"token": SAMPLE_BOT_TOKEN},
        )
    assert post_resp.status_code == 200

    # Now delete
    resp = await client.delete("/auth/telegram-bot")
    assert resp.status_code == 200

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT bot_token_encrypted, webhook_secret FROM telegram_connections "
            "WHERE user_id = $1::uuid",
            TEST_USER_ID,
        )
    assert row is not None
    assert row["bot_token_encrypted"] is None
    assert row["webhook_secret"] is None


async def test_delete_telegram_bot_no_connection_row_returns_200(telegram_bot_client):
    """DELETE when user has no telegram_connections row still returns 200."""
    client, _ = telegram_bot_client
    resp = await client.delete("/auth/telegram-bot")
    assert resp.status_code == 200


async def test_delete_telegram_bot_deregister_webhook_called(
    telegram_bot_client_with_existing_connection, pool, monkeypatch
):
    """DELETE calls deregister_webhook when TELEGRAM_WEBHOOK_URL is set and
    webhook_setup is importable."""
    client, fernet = telegram_bot_client_with_existing_connection
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com")

    # First set a bot token
    mock_resp = _make_mock_httpx_response(SAMPLE_GET_ME_RESPONSE)
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        await client.post(
            "/auth/telegram-bot",
            json={"token": SAMPLE_BOT_TOKEN},
        )

    deregister_called: list[str] = []

    async def mock_deregister(bot_token: str) -> None:
        deregister_called.append(bot_token)

    mock_module = MagicMock()
    mock_module.deregister_webhook = mock_deregister

    with patch.dict("sys.modules", {"bot.webhook_setup": mock_module}):
        resp = await client.delete("/auth/telegram-bot")

    assert resp.status_code == 200
    assert len(deregister_called) == 1
    assert deregister_called[0] == SAMPLE_BOT_TOKEN


# ---------------------------------------------------------------------------
# GET /api/auth/telegram-bot — status
# ---------------------------------------------------------------------------


async def test_get_telegram_bot_not_connected_no_row(telegram_bot_client):
    """User with no telegram_connections row → connected:false."""
    client, _ = telegram_bot_client
    resp = await client.get("/auth/telegram-bot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["bot_username"] is None


async def test_get_telegram_bot_not_connected_no_token(
    telegram_bot_client_with_existing_connection,
):
    """User with telegram_connections row but no bot_token → connected:false."""
    client, _ = telegram_bot_client_with_existing_connection
    resp = await client.get("/auth/telegram-bot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["bot_username"] is None


async def test_get_telegram_bot_connected_returns_username(
    telegram_bot_client_with_existing_connection,
):
    """User with bot token set → connected:true, bot_username from getMe."""
    client, _ = telegram_bot_client_with_existing_connection

    # First store a token
    mock_resp = _make_mock_httpx_response(SAMPLE_GET_ME_RESPONSE)
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        await client.post(
            "/auth/telegram-bot",
            json={"token": SAMPLE_BOT_TOKEN},
        )

    # Now GET — should call getMe again
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        resp = await client.get("/auth/telegram-bot")

    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["bot_username"] == "@testbot"
