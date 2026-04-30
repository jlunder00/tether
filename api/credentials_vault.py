"""Credentials vault — encrypt/decrypt per-user OAuth tokens.

Stores Anthropic OAuth credentials as a Fernet-encrypted JSON blob in the
``user_integrations.credentials_blob`` column. On use, decrypts the blob and
yields an env dict suitable for spawning ``claude-code`` (or the agent SDK,
which spawns claude-code internally) — the CLI reads ``CLAUDE_CODE_OAUTH_TOKEN``
before falling back to a credentials file on disk, so we never need to write
one.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from cryptography.fernet import Fernet

import db.postgres as db_pg
from db.pg_queries.integrations import (
    delete_credentials_blob,
    get_credentials_blob,
    store_credentials_blob,
)

logger = logging.getLogger(__name__)


class CredentialsVault:
    """Fernet-encrypted credentials store backed by Postgres."""

    # Per-user asyncio locks — shared across all vault instances so that a
    # reconstructed vault still serialises correctly within the same process.
    _locks: dict[str, asyncio.Lock] = {}

    def __init__(self, pool, encryption_key: bytes) -> None:
        self._pool = pool
        self._fernet = Fernet(encryption_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def materialize(self, user_id: str) -> AsyncIterator[dict[str, str]]:
        """Decrypt credentials_blob → yield env dict for claude-code subprocess.

        The yielded dict is intended to be merged into the env passed to
        ``ClaudeAgentOptions(env=...)`` or ``subprocess.Popen``. The CLI reads
        ``CLAUDE_CODE_OAUTH_TOKEN`` before consulting the on-disk credentials
        file, so the token never needs to touch the filesystem.
        """
        async with db_pg.get_conn(self._pool, user_id=user_id) as conn:
            blob = await get_credentials_blob(conn, user_id)

        if blob is None:
            raise ValueError(f"No credentials found for user {user_id}")

        plaintext = self._fernet.decrypt(blob)
        try:
            data = json.loads(plaintext.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"Malformed credentials blob for user {user_id}") from e

        token = data.get("oauth_token") if isinstance(data, dict) else None
        if not token:
            raise ValueError(
                f"Credentials blob for user {user_id} missing 'oauth_token' field"
            )

        yield {"CLAUDE_CODE_OAUTH_TOKEN": token}

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
