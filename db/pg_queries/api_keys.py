"""API key CRUD — create, list, revoke, validate.

validate_key uses an unscoped connection (no RLS) because it bootstraps
identity from the key itself before user_id is known.

All other operations are user-scoped and should use an RLS connection.
"""
from __future__ import annotations

import hashlib
import os
import uuid as _uuid

import asyncpg


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_key() -> str:
    """Generate a random API key in ttr_<urlsafe-base64-32bytes> format."""
    import base64
    raw = os.urandom(32)
    suffix = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return f"ttr_{suffix}"


def _row(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    return {k: str(v) if isinstance(v, _uuid.UUID) else v for k, v in d.items()}


def _rows(rows) -> list[dict]:
    return [_row(r) for r in rows]


async def count_active_keys(
    conn: asyncpg.Connection,
    user_id: str,
) -> int:
    """Return the number of active (non-revoked) keys for a user."""
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS n FROM api_keys WHERE user_id = $1::uuid AND revoked_at IS NULL",
        user_id,
    )
    return int(row["n"])


async def create_key(
    conn: asyncpg.Connection,
    user_id: str,
    name: str,
) -> tuple[str, dict]:
    """Generate a new API key. Returns (raw_key, record). raw_key is shown only once."""
    raw_key = _generate_key()
    key_hash = _hash(raw_key)
    key_prefix = raw_key[:8]

    row = await conn.fetchrow(
        """
        INSERT INTO api_keys (user_id, name, key_hash, key_prefix)
        VALUES ($1::uuid, $2, $3, $4)
        RETURNING id, user_id, name, key_prefix, created_at, last_used_at, revoked_at
        """,
        user_id, name, key_hash, key_prefix,
    )
    record = _row(row)
    return raw_key, record


async def list_keys(
    conn: asyncpg.Connection,
    user_id: str,
) -> list[dict]:
    """List all keys for a user. Never returns key_hash."""
    rows = await conn.fetch(
        """
        SELECT id, user_id, name, key_prefix, created_at, last_used_at, revoked_at
        FROM api_keys
        WHERE user_id = $1::uuid
        ORDER BY created_at DESC
        """,
        user_id,
    )
    return _rows(rows)


async def revoke_key(
    conn: asyncpg.Connection,
    key_id: str,
    user_id: str,
) -> None:
    """Revoke a key. No-op if key_id doesn't belong to user_id."""
    await conn.execute(
        """
        UPDATE api_keys
        SET revoked_at = now()
        WHERE id = $1::uuid AND user_id = $2::uuid AND revoked_at IS NULL
        """,
        key_id, user_id,
    )


async def validate_key(
    conn: asyncpg.Connection,
    raw_key: str,
) -> str | None:
    """Validate a raw API key and return the user_id, or None if invalid/revoked.

    Delegates to the validate_api_key() SECURITY DEFINER SQL function which
    executes as the function owner (superuser, BYPASSRLS). This is required
    because api_keys has RLS enabled and validate_key is called on an unscoped
    connection before a user_id is known.

    The function also updates last_used_at atomically for valid keys.
    """
    key_hash = _hash(raw_key)
    row = await conn.fetchrow("SELECT validate_api_key($1) AS user_id", key_hash)
    if row is None or row["user_id"] is None:
        return None
    return str(row["user_id"])
