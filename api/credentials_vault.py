"""Credentials vault — encrypt/decrypt per-user credentials blobs.

Stores Anthropic OAuth credentials as Fernet-encrypted bytes in the
user_integrations.credentials_blob column. On use, decrypts to a temp
directory, yields the path, then reads back and re-persists if the content
changed (i.e. token was refreshed by the caller).
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from cryptography.fernet import Fernet

import db.postgres as db_pg
from db.pg_queries.integrations import (
    delete_credentials_blob,
    get_credentials_blob,
    store_credentials_blob,
)

logger = logging.getLogger(__name__)

# Default runtime directory for materialized credentials.
# systemd RuntimeDirectory=tether/creds creates /run/tether/creds owned by the
# service user. Dockerfile / CI must create this directory or set creds_dir.
_DEFAULT_CREDS_DIR = Path("/run/tether/creds")


class CredentialsVault:
    """Fernet-encrypted credentials store backed by Postgres."""

    # Per-user asyncio locks — shared across all vault instances so that a
    # reconstructed vault still serialises correctly within the same process.
    _locks: dict[str, asyncio.Lock] = {}

    def __init__(
        self,
        pool,
        encryption_key: bytes,
        *,
        creds_dir: Path = _DEFAULT_CREDS_DIR,
    ) -> None:
        self._pool = pool
        self._fernet = Fernet(encryption_key)
        self._creds_dir = creds_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def materialize(self, user_id: str) -> AsyncIterator[Path]:
        """Decrypt credentials_blob → temp dir → yield → persist if changed → rmtree.

        The temp directory is always removed in the finally block, even if an
        exception is raised inside the `async with` block.
        """
        self._creds_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        subdir_name = secrets.token_hex(16)
        subdir = self._creds_dir / subdir_name
        subdir.mkdir(mode=0o700)

        creds_file = subdir / ".credentials.json"

        try:
            # Decrypt and write credentials
            async with db_pg.get_conn(self._pool, user_id=user_id) as conn:
                blob = await get_credentials_blob(conn, user_id)

            if blob is None:
                raise ValueError(f"No credentials_blob found for user {user_id}")

            plaintext = self._fernet.decrypt(blob)
            creds_file.write_bytes(plaintext)
            original_bytes = plaintext

            yield subdir

            # Read back — persist if content changed
            if creds_file.exists():
                current_bytes = creds_file.read_bytes()
                if current_bytes != original_bytes:
                    new_blob = self._fernet.encrypt(current_bytes)
                    async with db_pg.get_conn(self._pool, user_id=user_id) as conn:
                        await store_credentials_blob(conn, user_id, new_blob)
        finally:
            shutil.rmtree(subdir, ignore_errors=True)

    async def is_connected(self, user_id: str) -> bool:
        """True if user has a non-null credentials_blob for the anthropic provider."""
        async with db_pg.get_conn(self._pool, user_id=user_id) as conn:
            blob = await get_credentials_blob(conn, user_id)
        return blob is not None

    async def disconnect(self, user_id: str) -> None:
        """Delete the anthropic integration row for user_id."""
        async with db_pg.get_conn(self._pool, user_id=user_id) as conn:
            await delete_credentials_blob(conn, user_id)

    @asynccontextmanager
    async def with_lock(self, user_id: str) -> AsyncIterator[None]:
        """Acquire the per-user asyncio lock. Serialises concurrent vault operations."""
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            yield

    async def store_initial(self, user_id: str, credentials_dict: dict) -> None:
        """Serialize dict → JSON bytes → Fernet-encrypt → store via store_credentials_blob."""
        plaintext = json.dumps(credentials_dict).encode()
        blob = self._fernet.encrypt(plaintext)
        async with db_pg.get_conn(self._pool, user_id=user_id) as conn:
            await store_credentials_blob(conn, user_id, blob)
