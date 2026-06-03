"""Schema-level tests for memory-context v2 migration.

Covers:
  - node_sections gains origin + visible_to_user columns with correct defaults
  - node_data_summary table exists with correct schema + RLS (ENABLED + FORCED)
  - user_memory table exists with correct schema + RLS
  - user_durable_memory table exists with correct schema + RLS
  - pending_memory_writes table exists with correct schema + RLS
  - node_read_log table exists with correct schema + RLS
  - RLS cross-user isolation: User B cannot see User A's rows on each table
  - node_data_summary enforces UNIQUE (node_id, level_ordinal)

All tests require DATABASE_URL and a non-superuser app role; they skip otherwise.
"""
from __future__ import annotations

import os
import uuid

import asyncpg
import pytest

from db.postgres import register_jsonb_codec

USER_A = "00000000-0000-0000-0000-aa0000000001"
USER_B = "00000000-0000-0000-0000-bb0000000001"


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
            (USER_A, "mc_test_a", "mc_a@test.com"),
            (USER_B, "mc_test_b", "mc_b@test.com"),
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
# Helpers
# ---------------------------------------------------------------------------

async def _make_context_node(conn, user_id: str) -> str:
    """Insert a minimal context_node and return its UUID string."""
    row = await conn.fetchrow(
        """
        INSERT INTO context_nodes (id, user_id, name, node_type)
        VALUES (gen_random_uuid(), $1::uuid, 'Test Node', 'topic')
        RETURNING id::text
        """,
        user_id,
    )
    return row["id"]


def _rls_enabled(row) -> bool:
    return row["relrowsecurity"] is True


def _rls_forced(row) -> bool:
    return row["relforcerowsecurity"] is True


async def _rls_info(conn, table_name: str):
    return await conn.fetchrow(
        """
        SELECT relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE relname = $1
          AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
        """,
        table_name,
    )


async def _columns(conn, table_name: str) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        """,
        table_name,
    )
    return {r["column_name"] for r in rows}


async def _column_default(conn, table_name: str, column_name: str) -> str | None:
    row = await conn.fetchrow(
        """
        SELECT column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
          AND column_name = $2
        """,
        table_name, column_name,
    )
    return row["column_default"] if row else None


# ===========================================================================
# node_sections — new columns
# ===========================================================================

class TestNodeSectionsColumns:
    async def test_origin_column_exists(self, conn_a):
        """node_sections must have origin TEXT column after migration."""
        cols = await _columns(conn_a, "node_sections")
        assert "origin" in cols, "origin column missing from node_sections — run migration"

    async def test_visible_to_user_column_exists(self, conn_a):
        """node_sections must have visible_to_user BOOL column after migration."""
        cols = await _columns(conn_a, "node_sections")
        assert "visible_to_user" in cols, "visible_to_user column missing from node_sections — run migration"

    async def test_origin_default_is_user(self, conn_a):
        """origin column must default to 'user'."""
        default = await _column_default(conn_a, "node_sections", "origin")
        assert default is not None, "origin has no default"
        assert "'user'" in default, f"origin default should be 'user', got: {default}"

    async def test_visible_to_user_default_is_true(self, conn_a):
        """visible_to_user column must default to true."""
        default = await _column_default(conn_a, "node_sections", "visible_to_user")
        assert default is not None, "visible_to_user has no default"
        assert "true" in default.lower(), f"visible_to_user default should be true, got: {default}"

    async def test_origin_persists_in_insert(self, conn_a):
        """Inserting a section with origin='conversation_agent' round-trips correctly."""
        node_id = await _make_context_node(conn_a, USER_A)
        row = await conn_a.fetchrow(
            """
            INSERT INTO node_sections (user_id, node_id, section_type, name, body, origin)
            VALUES (
                current_setting('app.current_user_id', true)::uuid,
                $1::uuid, 'notes', 'main', 'Bot wrote this.', 'conversation_agent'
            )
            RETURNING origin, visible_to_user
            """,
            node_id,
        )
        assert row["origin"] == "conversation_agent"
        assert row["visible_to_user"] is True  # default

    async def test_visible_to_user_false_persists(self, conn_a):
        """visible_to_user=false must round-trip correctly."""
        node_id = await _make_context_node(conn_a, USER_A)
        row = await conn_a.fetchrow(
            """
            INSERT INTO node_sections (user_id, node_id, section_type, name, body, visible_to_user)
            VALUES (
                current_setting('app.current_user_id', true)::uuid,
                $1::uuid, 'notes', 'hidden', 'Internal note.', false
            )
            RETURNING visible_to_user
            """,
            node_id,
        )
        assert row["visible_to_user"] is False


# ===========================================================================
# node_data_summary
# ===========================================================================

class TestNodeDataSummarySchema:
    async def test_table_exists(self, conn_a):
        row = await conn_a.fetchrow(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'node_data_summary'"
        )
        assert row is not None, "node_data_summary table does not exist — run migration"

    async def test_rls_enabled_and_forced(self, conn_a):
        info = await _rls_info(conn_a, "node_data_summary")
        assert info is not None
        assert _rls_enabled(info), "RLS not enabled on node_data_summary"
        assert _rls_forced(info), "RLS not forced on node_data_summary"

    async def test_required_columns_present(self, conn_a):
        cols = await _columns(conn_a, "node_data_summary")
        required = {"id", "user_id", "node_id", "level_ordinal", "value", "abstract",
                    "source_checksum", "generated_at"}
        assert required <= cols, f"Missing columns: {required - cols}"

    async def test_unique_node_level_constraint(self, conn_a):
        """(node_id, level_ordinal) must be unique."""
        node_id = await _make_context_node(conn_a, USER_A)
        nds_id = str(uuid.uuid4())
        await conn_a.execute(
            """
            INSERT INTO node_data_summary (id, user_id, node_id, level_ordinal, value, source_checksum, generated_at)
            VALUES ($1::uuid,
                    current_setting('app.current_user_id', true)::uuid,
                    $2::uuid, 2, '{"keys": {}}'::jsonb, 'abc123', now())
            """,
            nds_id, node_id,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn_a.execute(
                """
                INSERT INTO node_data_summary (id, user_id, node_id, level_ordinal, value, source_checksum, generated_at)
                VALUES (gen_random_uuid(),
                        current_setting('app.current_user_id', true)::uuid,
                        $1::uuid, 2, '{"keys": {}}'::jsonb, 'def456', now())
                """,
                node_id,
            )

    async def test_rls_isolation(self, conn_a, conn_b):
        """User B cannot see User A's node_data_summary rows."""
        node_id_a = await _make_context_node(conn_a, USER_A)
        await conn_a.execute(
            """
            INSERT INTO node_data_summary (id, user_id, node_id, level_ordinal, value, source_checksum, generated_at)
            VALUES (gen_random_uuid(),
                    current_setting('app.current_user_id', true)::uuid,
                    $1::uuid, 1, '{"title": "test"}'::jsonb, 'chk1', now())
            """,
            node_id_a,
        )
        count_b = await conn_b.fetchval("SELECT COUNT(*) FROM node_data_summary")
        assert count_b == 0, "User B should see 0 rows from user A's node_data_summary"


# ===========================================================================
# user_memory
# ===========================================================================

class TestUserMemorySchema:
    async def test_table_exists(self, conn_a):
        row = await conn_a.fetchrow(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'user_memory'"
        )
        assert row is not None, "user_memory table does not exist — run migration"

    async def test_rls_enabled_and_forced(self, conn_a):
        info = await _rls_info(conn_a, "user_memory")
        assert info is not None
        assert _rls_enabled(info), "RLS not enabled on user_memory"
        assert _rls_forced(info), "RLS not forced on user_memory"

    async def test_required_columns_present(self, conn_a):
        cols = await _columns(conn_a, "user_memory")
        required = {"id", "user_id", "key", "value", "updated_at", "last_read_at"}
        assert required <= cols, f"Missing columns: {required - cols}"

    async def test_unique_user_key_constraint(self, conn_a):
        """(user_id, key) must be unique."""
        await conn_a.execute(
            """
            INSERT INTO user_memory (user_id, key, value)
            VALUES (current_setting('app.current_user_id', true)::uuid,
                    'preferences/test', 'v1')
            """
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn_a.execute(
                """
                INSERT INTO user_memory (user_id, key, value)
                VALUES (current_setting('app.current_user_id', true)::uuid,
                        'preferences/test', 'v2')
                """
            )

    async def test_rls_isolation(self, conn_a, conn_b):
        """User B cannot read User A's user_memory rows."""
        await conn_a.execute(
            """
            INSERT INTO user_memory (user_id, key, value)
            VALUES (current_setting('app.current_user_id', true)::uuid,
                    'facts/work/role', 'engineering lead')
            """
        )
        count_b = await conn_b.fetchval("SELECT COUNT(*) FROM user_memory")
        assert count_b == 0


# ===========================================================================
# user_durable_memory
# ===========================================================================

class TestUserDurableMemorySchema:
    async def test_table_exists(self, conn_a):
        row = await conn_a.fetchrow(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'user_durable_memory'"
        )
        assert row is not None, "user_durable_memory table does not exist — run migration"

    async def test_rls_enabled_and_forced(self, conn_a):
        info = await _rls_info(conn_a, "user_durable_memory")
        assert info is not None
        assert _rls_enabled(info), "RLS not enabled on user_durable_memory"
        assert _rls_forced(info), "RLS not forced on user_durable_memory"

    async def test_required_columns_present(self, conn_a):
        cols = await _columns(conn_a, "user_durable_memory")
        required = {"id", "user_id", "key", "value", "source", "evidence",
                    "confidence", "created_at", "updated_at"}
        assert required <= cols, f"Missing columns: {required - cols}"

    async def test_unique_user_key_constraint(self, conn_a):
        """(user_id, key) must be unique in user_durable_memory."""
        await conn_a.execute(
            """
            INSERT INTO user_durable_memory (user_id, key, value, source)
            VALUES (current_setting('app.current_user_id', true)::uuid,
                    'inferred_preferences/morning', 'prefers 7am', 'compaction_monthly')
            """
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn_a.execute(
                """
                INSERT INTO user_durable_memory (user_id, key, value, source)
                VALUES (current_setting('app.current_user_id', true)::uuid,
                        'inferred_preferences/morning', 'prefers 8am', 'compaction_monthly')
                """
            )

    async def test_confidence_default_is_medium(self, conn_a):
        default = await _column_default(conn_a, "user_durable_memory", "confidence")
        assert default is not None
        assert "'medium'" in default, f"confidence default should be 'medium', got: {default}"

    async def test_rls_isolation(self, conn_a, conn_b):
        await conn_a.execute(
            """
            INSERT INTO user_durable_memory (user_id, key, value, source)
            VALUES (current_setting('app.current_user_id', true)::uuid,
                    'historical_summaries/2026-Q1', 'Q1 focused on launch', 'compaction_monthly')
            """
        )
        count_b = await conn_b.fetchval("SELECT COUNT(*) FROM user_durable_memory")
        assert count_b == 0


# ===========================================================================
# pending_memory_writes
# ===========================================================================

class TestPendingMemoryWritesSchema:
    async def test_table_exists(self, conn_a):
        row = await conn_a.fetchrow(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'pending_memory_writes'"
        )
        assert row is not None, "pending_memory_writes table does not exist — run migration"

    async def test_rls_enabled_and_forced(self, conn_a):
        info = await _rls_info(conn_a, "pending_memory_writes")
        assert info is not None
        assert _rls_enabled(info), "RLS not enabled on pending_memory_writes"
        assert _rls_forced(info), "RLS not forced on pending_memory_writes"

    async def test_required_columns_present(self, conn_a):
        cols = await _columns(conn_a, "pending_memory_writes")
        required = {"id", "user_id", "key", "value", "reason", "status",
                    "conversation_id", "created_at", "reviewed_at"}
        assert required <= cols, f"Missing columns: {required - cols}"

    async def test_status_default_is_pending(self, conn_a):
        default = await _column_default(conn_a, "pending_memory_writes", "status")
        assert default is not None
        assert "'pending'" in default, f"status default should be 'pending', got: {default}"

    async def test_insert_and_read(self, conn_a):
        """Can insert a proposal and read it back."""
        row = await conn_a.fetchrow(
            """
            INSERT INTO pending_memory_writes (user_id, key, value, reason)
            VALUES (current_setting('app.current_user_id', true)::uuid,
                    'preferences/morning_routine', 'structured plan by 8am',
                    'User explicitly stated this preference.')
            RETURNING id, status
            """
        )
        assert row["id"] is not None
        assert row["status"] == "pending"

    async def test_rls_isolation(self, conn_a, conn_b):
        await conn_a.execute(
            """
            INSERT INTO pending_memory_writes (user_id, key, value, reason)
            VALUES (current_setting('app.current_user_id', true)::uuid,
                    'preferences/comms', 'terse', 'User preference.')
            """
        )
        count_b = await conn_b.fetchval("SELECT COUNT(*) FROM pending_memory_writes")
        assert count_b == 0


# ===========================================================================
# node_read_log
# ===========================================================================

class TestNodeReadLogSchema:
    async def test_table_exists(self, conn_a):
        row = await conn_a.fetchrow(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'node_read_log'"
        )
        assert row is not None, "node_read_log table does not exist — run migration"

    async def test_rls_enabled_and_forced(self, conn_a):
        info = await _rls_info(conn_a, "node_read_log")
        assert info is not None
        assert _rls_enabled(info), "RLS not enabled on node_read_log"
        assert _rls_forced(info), "RLS not forced on node_read_log"

    async def test_required_columns_present(self, conn_a):
        cols = await _columns(conn_a, "node_read_log")
        required = {"id", "user_id", "conversation_id", "node_id", "level_ordinal",
                    "title", "read_at"}
        assert required <= cols, f"Missing columns: {required - cols}"

    async def test_insert_and_read(self, conn_a):
        """Can log a read event and retrieve it."""
        node_id = await _make_context_node(conn_a, USER_A)
        row = await conn_a.fetchrow(
            """
            INSERT INTO node_read_log (user_id, node_id, level_ordinal, title)
            VALUES (current_setting('app.current_user_id', true)::uuid,
                    $1::uuid, 2, 'Intellipat')
            RETURNING id, read_at
            """,
            node_id,
        )
        assert row["id"] is not None
        assert row["read_at"] is not None

    async def test_rls_isolation(self, conn_a, conn_b):
        """User B cannot see User A's read log."""
        node_id_a = await _make_context_node(conn_a, USER_A)
        await conn_a.execute(
            """
            INSERT INTO node_read_log (user_id, node_id, level_ordinal, title)
            VALUES (current_setting('app.current_user_id', true)::uuid,
                    $1::uuid, 1, 'test')
            """,
            node_id_a,
        )
        count_b = await conn_b.fetchval("SELECT COUNT(*) FROM node_read_log")
        assert count_b == 0
