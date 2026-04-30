"""Unit tests for CredentialsVault — env-dict materialize() contract.

`materialize()` decrypts the stored credentials blob and yields an env dict
suitable for spawning claude-code as a subprocess. The Anthropic SDK / CLI
reads ``CLAUDE_CODE_OAUTH_TOKEN`` before falling back to the credentials file.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet


# ---------------------------------------------------------------------------
# 1. Fernet roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fernet_roundtrip():
    key = Fernet.generate_key()
    f = Fernet(key)

    original = {"oauth_token": "sk-ant-oat01-abc123", "refreshed": True}
    plaintext = json.dumps(original).encode()
    encrypted = f.encrypt(plaintext)
    decrypted = json.loads(f.decrypt(encrypted).decode())

    assert decrypted == original


# ---------------------------------------------------------------------------
# 2. store_initial + materialize roundtrip — yields env dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_and_materialize_yields_env_dict():
    """materialize yields {'CLAUDE_CODE_OAUTH_TOKEN': <token>} from stored blob."""
    from api.credentials_vault import CredentialsVault

    key = Fernet.generate_key()
    vault = CredentialsVault(pool=None, encryption_key=key)

    stored_blob: list[bytes] = []

    async def fake_store(conn, user_id, blob):
        stored_blob.append(blob)

    async def fake_get(conn, user_id):
        return stored_blob[-1] if stored_blob else None

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield AsyncMock()

    with patch("api.credentials_vault.store_credentials_blob", side_effect=fake_store), \
         patch("api.credentials_vault.get_credentials_blob", side_effect=fake_get), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):

        await vault.store_initial("user1", {"oauth_token": "sk-ant-oat01-XYZ"})

        async with vault.materialize("user1") as env:
            assert isinstance(env, dict)
            assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-XYZ"}


# ---------------------------------------------------------------------------
# 3. materialize raises when blob is missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_materialize_raises_when_blob_missing():
    from api.credentials_vault import CredentialsVault

    vault = CredentialsVault(pool=None, encryption_key=Fernet.generate_key())

    async def fake_get(conn, user_id):
        return None

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield AsyncMock()

    with patch("api.credentials_vault.get_credentials_blob", side_effect=fake_get), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):
        with pytest.raises(ValueError, match="No credentials"):
            async with vault.materialize("user1"):
                pass


# ---------------------------------------------------------------------------
# 4. materialize raises when blob is malformed (no oauth_token field)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_materialize_raises_on_missing_oauth_token_field():
    from api.credentials_vault import CredentialsVault

    key = Fernet.generate_key()
    vault = CredentialsVault(pool=None, encryption_key=key)

    bad_blob = Fernet(key).encrypt(json.dumps({"unrelated": "data"}).encode())

    async def fake_get(conn, user_id):
        return bad_blob

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield AsyncMock()

    with patch("api.credentials_vault.get_credentials_blob", side_effect=fake_get), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):
        with pytest.raises(ValueError, match="oauth_token"):
            async with vault.materialize("user1"):
                pass


# ---------------------------------------------------------------------------
# 5. disconnect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disconnect_calls_delete():
    from api.credentials_vault import CredentialsVault

    vault = CredentialsVault(pool=None, encryption_key=Fernet.generate_key())

    deleted: list[str] = []

    async def fake_delete(conn, user_id):
        deleted.append(user_id)

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield AsyncMock()

    with patch("api.credentials_vault.delete_credentials_blob", side_effect=fake_delete), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):
        await vault.disconnect("user42")

    assert deleted == ["user42"]


# ---------------------------------------------------------------------------
# 6. with_lock serializes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_with_lock_serializes():
    from api.credentials_vault import CredentialsVault

    vault = CredentialsVault(pool=None, encryption_key=Fernet.generate_key())

    order: list[str] = []

    async def task_a():
        async with vault.with_lock("user1"):
            order.append("a_enter")
            await asyncio.sleep(0.01)
            order.append("a_exit")

    async def task_b():
        async with vault.with_lock("user1"):
            order.append("b_enter")
            await asyncio.sleep(0.01)
            order.append("b_exit")

    await asyncio.gather(task_a(), task_b())

    assert order in [
        ["a_enter", "a_exit", "b_enter", "b_exit"],
        ["b_enter", "b_exit", "a_enter", "a_exit"],
    ]


# ---------------------------------------------------------------------------
# 7. cfg.VAULT_KEY roundtrip — operator-supplied key works through full pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cfg_vault_key_roundtrip(monkeypatch):
    raw_key = Fernet.generate_key()
    monkeypatch.setenv("TETHER_VAULT_KEY", raw_key.decode())

    from config import loader as config_loader
    config_loader.config._cfg = None

    import importlib
    import api.config as cfg
    importlib.reload(cfg)

    assert cfg.VAULT_KEY is not None

    from api.credentials_vault import CredentialsVault

    vault = CredentialsVault(pool=None, encryption_key=cfg.VAULT_KEY)

    stored: list[bytes] = []

    async def fake_store(conn, user_id, blob):
        stored.append(blob)

    async def fake_get(conn, user_id):
        return stored[-1] if stored else None

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield AsyncMock()

    with patch("api.credentials_vault.store_credentials_blob", side_effect=fake_store), \
         patch("api.credentials_vault.get_credentials_blob", side_effect=fake_get), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):

        await vault.store_initial("user1", {"oauth_token": "sk-ant-oat01-roundtrip"})
        async with vault.materialize("user1") as env:
            assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-roundtrip"
