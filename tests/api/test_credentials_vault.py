"""Unit tests for CredentialsVault — no live database required.

TDD: written before implementation, confirmed to fail for the right reason
(ModuleNotFoundError / ImportError) before api/credentials_vault.py exists.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from cryptography.fernet import Fernet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(pool=None, creds_dir: Path | None = None):
    """Return a CredentialsVault with a fresh Fernet key and optional creds_dir."""
    from api.credentials_vault import CredentialsVault

    key = Fernet.generate_key()
    kwargs = {}
    if creds_dir is not None:
        kwargs["creds_dir"] = creds_dir
    return CredentialsVault(pool, key, **kwargs)


@asynccontextmanager
async def _fake_get_conn(blob: bytes | None):
    """Context manager that fakes db.postgres.get_conn and returns a mock conn
    whose fetchrow returns a record-like dict for credentials_blob."""
    conn = AsyncMock()

    async def fake_fetchrow(query, *args):
        if blob is None:
            return None
        # Return something with __getitem__ for ['credentials_blob']
        row = {"credentials_blob": blob}
        return row

    conn.fetchrow = fake_fetchrow
    conn.execute = AsyncMock(return_value=None)
    yield conn


# ---------------------------------------------------------------------------
# 1. Fernet roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fernet_roundtrip():
    """Encrypt then decrypt a known blob dict, verify identity."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    f = Fernet(key)

    original = {"api_key": "sk-ant-abc123", "refreshed": True}
    plaintext = json.dumps(original).encode()
    encrypted = f.encrypt(plaintext)
    decrypted = json.loads(f.decrypt(encrypted).decode())

    assert decrypted == original


# ---------------------------------------------------------------------------
# 2. store_initial + materialize roundtrip (mocked DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_and_retrieve_roundtrip(tmp_path):
    """store_initial encrypts the blob; materialize decrypts it back."""
    from api.credentials_vault import CredentialsVault

    key = Fernet.generate_key()
    vault = CredentialsVault(pool=None, encryption_key=key, creds_dir=tmp_path)

    original = {"anthropic_api_key": "sk-ant-test", "user": "u1"}
    stored_blob: list[bytes] = []

    async def fake_store(conn, user_id, blob):
        stored_blob.append(blob)

    async def fake_get(conn, user_id):
        return stored_blob[-1] if stored_blob else None

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        conn = AsyncMock()
        yield conn

    with patch("api.credentials_vault.store_credentials_blob", side_effect=fake_store), \
         patch("api.credentials_vault.get_credentials_blob", side_effect=fake_get), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):

        await vault.store_initial("user1", original)
        assert len(stored_blob) == 1

        # Now materialize and verify the decrypted JSON matches
        async with vault.materialize("user1") as creds_dir:
            creds_file = creds_dir / ".credentials.json"
            assert creds_file.exists()
            loaded = json.loads(creds_file.read_text())

    assert loaded == original


# ---------------------------------------------------------------------------
# 3. materialize persists when file content changed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_materialize_persists_when_changed(tmp_path):
    """If the credentials file is modified inside materialize, vault re-encrypts and stores."""
    from api.credentials_vault import CredentialsVault
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    vault = CredentialsVault(pool=None, encryption_key=key, creds_dir=tmp_path)

    original = {"token": "old_token"}
    f = Fernet(key)
    original_blob = f.encrypt(json.dumps(original).encode())

    stored_calls: list[bytes] = []

    async def fake_get(conn, user_id):
        return original_blob

    async def fake_store(conn, user_id, blob):
        stored_calls.append(blob)

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield AsyncMock()

    with patch("api.credentials_vault.get_credentials_blob", side_effect=fake_get), \
         patch("api.credentials_vault.store_credentials_blob", side_effect=fake_store), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):

        async with vault.materialize("user1") as creds_dir:
            creds_file = creds_dir / ".credentials.json"
            # Modify the file — simulate token refresh
            updated = {"token": "new_token"}
            creds_file.write_text(json.dumps(updated))

    # store should have been called once with new encrypted bytes
    assert len(stored_calls) == 1
    decrypted = json.loads(f.decrypt(stored_calls[0]).decode())
    assert decrypted == updated


# ---------------------------------------------------------------------------
# 4. materialize does NOT persist when file unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_materialize_no_persist_when_unchanged(tmp_path):
    """If credentials file is not modified, store_credentials_blob is NOT called."""
    from api.credentials_vault import CredentialsVault
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    vault = CredentialsVault(pool=None, encryption_key=key, creds_dir=tmp_path)

    original = {"token": "unchanged"}
    f = Fernet(key)
    original_blob = f.encrypt(json.dumps(original).encode())

    stored_calls: list = []

    async def fake_get(conn, user_id):
        return original_blob

    async def fake_store(conn, user_id, blob):
        stored_calls.append(blob)

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield AsyncMock()

    with patch("api.credentials_vault.get_credentials_blob", side_effect=fake_get), \
         patch("api.credentials_vault.store_credentials_blob", side_effect=fake_store), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):

        async with vault.materialize("user1") as creds_dir:
            # Do NOT modify the file
            pass

    assert len(stored_calls) == 0


# ---------------------------------------------------------------------------
# 5. materialize rmtree on exception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_materialize_rmtree_on_exception(tmp_path):
    """Even if an exception is raised inside materialize, the temp dir is cleaned up."""
    from api.credentials_vault import CredentialsVault
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    vault = CredentialsVault(pool=None, encryption_key=key, creds_dir=tmp_path)

    original = {"token": "abc"}
    f = Fernet(key)
    original_blob = f.encrypt(json.dumps(original).encode())

    captured_dir: list[Path] = []

    async def fake_get(conn, user_id):
        return original_blob

    @asynccontextmanager
    async def fake_get_conn(pool, user_id=None):
        yield AsyncMock()

    with patch("api.credentials_vault.get_credentials_blob", side_effect=fake_get), \
         patch("api.credentials_vault.store_credentials_blob", new=AsyncMock()), \
         patch("api.credentials_vault.db_pg.get_conn", fake_get_conn):

        with pytest.raises(ValueError, match="intentional"):
            async with vault.materialize("user1") as creds_dir:
                captured_dir.append(creds_dir)
                raise ValueError("intentional error")

    # The subdir should be gone
    assert len(captured_dir) == 1
    assert not captured_dir[0].exists()


# ---------------------------------------------------------------------------
# 6. disconnect calls delete_credentials_blob
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disconnect_calls_delete(tmp_path):
    """vault.disconnect calls delete_credentials_blob with correct user_id."""
    from api.credentials_vault import CredentialsVault

    key = Fernet.generate_key()
    vault = CredentialsVault(pool=None, encryption_key=key, creds_dir=tmp_path)

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
# 7. with_lock serializes concurrent access
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_with_lock_serializes(tmp_path):
    """Two concurrent coroutines acquiring the same user lock run sequentially."""
    from api.credentials_vault import CredentialsVault

    key = Fernet.generate_key()
    vault = CredentialsVault(pool=None, encryption_key=key, creds_dir=tmp_path)

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

    # Either a runs completely before b, or vice versa — they must NOT interleave
    assert order in [
        ["a_enter", "a_exit", "b_enter", "b_exit"],
        ["b_enter", "b_exit", "a_enter", "a_exit"],
    ]
