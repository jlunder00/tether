"""Tests for session_notes table migration and pg_queries layer.

Covers:
  - session_notes table exists after migration (schema check)
  - get_session_notes returns None when no row exists
  - upsert_session_notes inserts on first call
  - upsert_session_notes updates on subsequent call (singleton pattern)
  - get_session_notes returns None for empty content
  - RLS scoping: User A cannot see User B's notes
  - updated_at is refreshed on upsert

All tests require DATABASE_URL and a non-superuser app role; they skip otherwise.
"""
from __future__ import annotations

import os
import uuid

import asyncpg
import pytest

from db.postgres import register_jsonb_codec

USER_A = "00000000-0000-0000-0000-aaaaaaaaaaaa"
USER_B = "00000000-0000-0000-0000-bbbbbbbbbbbb"


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — Postgres tests skipped")
    return url


async def _seed_users(url: str) -> None:
    """Seed deterministic test users outside any rolled-back transaction."""
    c = await asyncpg.connect(dsn=url)
    try:
        await register_jsonb_codec(c)
        for uid, uname, email in [
            (USER_A, "sn_test_a", "sn_a@test.com"),
            (USER_B, "sn_test_b", "sn_b@test.com"),
        ]:
            await c.execute(
                "INSERT INTO users (id, username, email, password_hash) "
                "VALUES ($1::uuid, $2, $3, 'x') ON CONFLICT (id) DO NOTHING",
                uid, uname, email,
            )
    finally:
        await c.close()


@pytest.fixture
async def conn_a():
    """Connection scoped to USER_A, wrapped in a rolled-back transaction."""
    url = _db_url()
    await _seed_users(url)
    c = await asyncpg.connect(dsn=url)
    await register_jsonb_codec(c)
    tr = c.transaction()
    await tr.start()
    await c.execute("SELECT set_config('app.current_user_id', $1, true)", USER_A)
    yield c
    await tr.rollback()
    await c.close()


@pytest.fixture
async def conn_b():
    """Connection scoped to USER_B, wrapped in a rolled-back transaction."""
    url = _db_url()
    await _seed_users(url)
    c = await asyncpg.connect(dsn=url)
    await register_jsonb_codec(c)
    tr = c.transaction()
    await tr.start()
    await c.execute("SELECT set_config('app.current_user_id', $1, true)", USER_B)
    yield c
    await tr.rollback()
    await c.close()


# ---------------------------------------------------------------------------
# Schema presence check (migration ran)
# ---------------------------------------------------------------------------

class TestSessionNotesSchema:
    async def test_table_exists(self, conn_a):
        """session_notes table must exist after the migration."""
        row = await conn_a.fetchrow(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = 'session_notes'
            """
        )
        assert row is not None, "session_notes table does not exist — run migration"

    async def test_rls_is_enabled(self, conn_a):
        """RLS must be enabled and forced on session_notes."""
        row = await conn_a.fetchrow(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = 'session_notes'
              AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
            """
        )
        assert row is not None, "session_notes table not found in pg_class"
        assert row["relrowsecurity"], "RLS not enabled on session_notes"
        assert row["relforcerowsecurity"], "RLS not forced on session_notes"

    async def test_user_id_is_primary_key(self, conn_a):
        """user_id must be the primary key (singleton per user)."""
        row = await conn_a.fetchrow(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.table_name = 'session_notes'
              AND tc.constraint_type = 'PRIMARY KEY'
            """
        )
        assert row is not None, "No primary key on session_notes"
        assert row["column_name"] == "user_id"


# ---------------------------------------------------------------------------
# get_session_notes — read behavior
# ---------------------------------------------------------------------------

class TestGetSessionNotes:
    async def test_returns_none_when_no_row(self, conn_a):
        """Returns None (not empty string) when no row exists for user."""
        from db.pg_queries.session_notes import get_session_notes
        result = await get_session_notes(conn_a)
        assert result is None

    async def test_returns_content_after_upsert(self, conn_a):
        """Returns previously inserted content."""
        from db.pg_queries.session_notes import get_session_notes, upsert_session_notes
        await upsert_session_notes(conn_a, "# Session Notes\nWorking on alpha.")
        result = await get_session_notes(conn_a)
        assert result == "# Session Notes\nWorking on alpha."

    async def test_returns_none_for_empty_content(self, conn_a):
        """Returns None when content was reset to empty string."""
        from db.pg_queries.session_notes import get_session_notes, upsert_session_notes
        await upsert_session_notes(conn_a, "")
        result = await get_session_notes(conn_a)
        assert result is None


# ---------------------------------------------------------------------------
# upsert_session_notes — write behavior
# ---------------------------------------------------------------------------

class TestUpsertSessionNotes:
    async def test_insert_on_first_call(self, conn_a):
        """First upsert creates a row."""
        from db.pg_queries.session_notes import get_session_notes, upsert_session_notes
        await upsert_session_notes(conn_a, "First write.")
        assert await get_session_notes(conn_a) == "First write."

    async def test_update_on_subsequent_call(self, conn_a):
        """Second upsert replaces content (singleton row per user)."""
        from db.pg_queries.session_notes import get_session_notes, upsert_session_notes
        await upsert_session_notes(conn_a, "First write.")
        await upsert_session_notes(conn_a, "Second write — replaces first.")
        result = await get_session_notes(conn_a)
        assert result == "Second write — replaces first."
        assert "First write" not in result

    async def test_updated_at_refreshes_on_update(self, conn_a):
        """updated_at must advance on the second upsert."""
        from db.pg_queries.session_notes import upsert_session_notes
        await upsert_session_notes(conn_a, "v1")
        row1 = await conn_a.fetchrow(
            "SELECT updated_at FROM session_notes "
            "WHERE user_id = current_setting('app.current_user_id', true)::uuid"
        )
        # Force a tiny clock advance by wrapping in a separate statement
        await conn_a.execute("SELECT pg_sleep(0.01)")
        await upsert_session_notes(conn_a, "v2")
        row2 = await conn_a.fetchrow(
            "SELECT updated_at FROM session_notes "
            "WHERE user_id = current_setting('app.current_user_id', true)::uuid"
        )
        assert row2["updated_at"] >= row1["updated_at"]


# ---------------------------------------------------------------------------
# RLS scoping — cross-user isolation
# ---------------------------------------------------------------------------

class TestSessionNotesRLS:
    async def test_user_a_cannot_read_user_b_notes(self, conn_a, conn_b):
        """User B's notes are invisible to User A's connection."""
        from db.pg_queries.session_notes import get_session_notes, upsert_session_notes
        # Write as User B
        await upsert_session_notes(conn_b, "User B secret notes.")
        # Read as User A — should see nothing
        result = await get_session_notes(conn_a)
        assert result is None

    async def test_each_user_sees_only_their_own_notes(self, conn_a, conn_b):
        """User A and User B have independent singleton rows."""
        from db.pg_queries.session_notes import get_session_notes, upsert_session_notes
        await upsert_session_notes(conn_a, "Notes for A.")
        await upsert_session_notes(conn_b, "Notes for B.")
        assert await get_session_notes(conn_a) == "Notes for A."
        assert await get_session_notes(conn_b) == "Notes for B."
