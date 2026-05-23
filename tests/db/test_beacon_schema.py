"""Schema-level tests for Beacon memory tables (Phase 3 prep).

Covers:
  - Each of the 6 Beacon tables can be inserted into and queried back
  - RLS scoping: User B cannot see User A's rows on any table
  - conversations.handle + expires_at columns exist and are nullable
  - conversations.state accepts 'pending' and 'rejected' in addition to existing values
  - beacon_memory enforces UNIQUE (user_id, key) constraint

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
            (USER_A, "beacon_test_a", "beacon_a@test.com"),
            (USER_B, "beacon_test_b", "beacon_b@test.com"),
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
# Helper: insert a conversation for a user (needed for beacon_dispatches FK)
# ---------------------------------------------------------------------------

async def _make_conversation(conn, user_id: str) -> str:
    """Insert a minimal conversation and return its UUID string."""
    row = await conn.fetchrow(
        """
        INSERT INTO conversations (user_id, name, type, priority, state)
        VALUES ($1::uuid, 'Beacon Test Conv', 'interactive', 'normal', 'open')
        RETURNING id::text
        """,
        user_id,
    )
    return row["id"]


# ===========================================================================
# beacon_dispatches
# ===========================================================================

class TestBeaconDispatches:
    async def test_insert_and_fetch(self, conn_a):
        conv_id = await _make_conversation(conn_a, USER_A)
        row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_dispatches
                (user_id, checkpoint_type, mode, conversation_id, priority)
            VALUES ($1::uuid, 'anchor_transition', 'reminders', $2::uuid, 'normal')
            RETURNING id, state, priority
            """,
            USER_A, conv_id,
        )
        assert row["state"] == "active"
        assert row["priority"] == "normal"

    async def test_rls_user_b_cannot_see_user_a_rows(self, conn_a, conn_b):
        """User B must not see User A's beacon_dispatches rows."""
        conv_id = await _make_conversation(conn_a, USER_A)
        dispatch_row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_dispatches
                (user_id, checkpoint_type, mode, conversation_id)
            VALUES ($1::uuid, 'eod', 'item_audit', $2::uuid)
            RETURNING id
            """,
            USER_A, conv_id,
        )
        dispatch_id = dispatch_row["id"]

        # User B's connection should return nothing
        row_b = await conn_b.fetchrow(
            "SELECT id FROM beacon_dispatches WHERE id = $1", dispatch_id
        )
        assert row_b is None, "RLS failed: user B can see user A's beacon_dispatches row"

    async def test_active_state_index_semantics(self, conn_a):
        """Rows with state='active' are retrievable; state='concluded' are not active."""
        conv_id = await _make_conversation(conn_a, USER_A)
        await conn_a.execute(
            """
            INSERT INTO beacon_dispatches
                (user_id, checkpoint_type, mode, conversation_id, state)
            VALUES ($1::uuid, 'task_overdue', 'reminders', $2::uuid, 'concluded')
            """,
            USER_A, conv_id,
        )
        active = await conn_a.fetch(
            "SELECT id FROM beacon_dispatches WHERE user_id = $1::uuid AND state = 'active'",
            USER_A,
        )
        # No active rows were inserted in this test
        assert len(active) == 0


# ===========================================================================
# beacon_decisions
# ===========================================================================

class TestBeaconDecisions:
    async def test_insert_and_fetch(self, conn_a):
        run_id = uuid.uuid4()
        row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_decisions
                (user_id, checkpoint_type, mode, action, reason, beacon_run_id)
            VALUES ($1::uuid, 'anchor_transition', 'reminders', 'silent_exit', 'no overdue tasks', $2)
            RETURNING id, action, decided_at
            """,
            USER_A, run_id,
        )
        assert row["action"] == "silent_exit"
        assert row["decided_at"] is not None

    async def test_rls_user_b_cannot_see_user_a_rows(self, conn_a, conn_b):
        run_id = uuid.uuid4()
        decision_row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_decisions
                (user_id, checkpoint_type, mode, action, beacon_run_id)
            VALUES ($1::uuid, 'eod', 'memory_audit', 'memory_only', $2)
            RETURNING id
            """,
            USER_A, run_id,
        )
        decision_id = decision_row["id"]
        row_b = await conn_b.fetchrow(
            "SELECT id FROM beacon_decisions WHERE id = $1", decision_id
        )
        assert row_b is None, "RLS failed: user B can see user A's beacon_decisions row"


# ===========================================================================
# beacon_suppressions
# ===========================================================================

class TestBeaconSuppressions:
    async def test_insert_and_fetch(self, conn_a):
        row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_suppressions
                (user_id, scope_key, reason, source)
            VALUES ($1::uuid, 'topic/morning', 'user rejected', 'user_rejection')
            RETURNING id, scope_key, source, expires_at
            """,
            USER_A,
        )
        assert row["scope_key"] == "topic/morning"
        assert row["source"] == "user_rejection"
        assert row["expires_at"] is None  # nullable

    async def test_rls_user_b_cannot_see_user_a_rows(self, conn_a, conn_b):
        sup_row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_suppressions
                (user_id, scope_key, source)
            VALUES ($1::uuid, 'conv/123', 'beacon_decision')
            RETURNING id
            """,
            USER_A,
        )
        sup_id = sup_row["id"]
        row_b = await conn_b.fetchrow(
            "SELECT id FROM beacon_suppressions WHERE id = $1", sup_id
        )
        assert row_b is None, "RLS failed: user B can see user A's beacon_suppressions row"


# ===========================================================================
# beacon_memory (L2)
# ===========================================================================

class TestBeaconMemory:
    async def test_insert_and_fetch(self, conn_a):
        row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_memory (user_id, key, value)
            VALUES ($1::uuid, 'patterns/morning/response_rate', '0.6')
            RETURNING id, key, value, updated_at
            """,
            USER_A,
        )
        assert row["key"] == "patterns/morning/response_rate"
        assert row["value"] == "0.6"
        assert row["updated_at"] is not None

    async def test_unique_key_per_user_enforced(self, conn_a):
        await conn_a.execute(
            "INSERT INTO beacon_memory (user_id, key, value) VALUES ($1::uuid, 'dup/key', 'v1')",
            USER_A,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn_a.execute(
                "INSERT INTO beacon_memory (user_id, key, value) VALUES ($1::uuid, 'dup/key', 'v2')",
                USER_A,
            )

    async def test_rls_user_b_cannot_see_user_a_rows(self, conn_a, conn_b):
        mem_row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_memory (user_id, key, value)
            VALUES ($1::uuid, 'preferences/ping_quiet', 'true')
            RETURNING id
            """,
            USER_A,
        )
        mem_id = mem_row["id"]
        row_b = await conn_b.fetchrow(
            "SELECT id FROM beacon_memory WHERE id = $1", mem_id
        )
        assert row_b is None, "RLS failed: user B can see user A's beacon_memory row"

    async def test_same_key_different_users_allowed(self, conn_a, conn_b):
        """Two users can have the same key — the UNIQUE constraint is (user_id, key)."""
        await conn_a.execute(
            "INSERT INTO beacon_memory (user_id, key, value) VALUES ($1::uuid, 'shared/key', 'from_a')",
            USER_A,
        )
        # Should not raise — different user_id
        await conn_b.execute(
            "INSERT INTO beacon_memory (user_id, key, value) VALUES ($1::uuid, 'shared/key', 'from_b')",
            USER_B,
        )

    async def test_rls_write_side_cannot_insert_for_other_user(self, conn_a):
        """RLS WITH CHECK: connection scoped to USER_A cannot INSERT a row owned by USER_B.

        FOR ALL USING (...) policies auto-set WITH CHECK = USING, so writes of
        cross-user rows are blocked. This test verifies that the write-side
        protection actually fires — it would pass even if policy was FOR SELECT
        only, which would be a security gap. We test here rather than for every
        table since beacon_memory is the highest-churn write surface.
        """
        with pytest.raises(Exception) as exc_info:
            await conn_a.execute(
                "INSERT INTO beacon_memory (user_id, key, value) VALUES ($1::uuid, 'attack/key', 'stolen')",
                USER_B,  # USER_B id while connected as USER_A
            )
        # asyncpg raises either InsufficientPrivilegeError (RLS policy violation)
        # or a generic PostgresError with "new row violates row-level security"
        assert "row-level security" in str(exc_info.value).lower() or \
               "insufficient_privilege" in str(exc_info.value).lower() or \
               type(exc_info.value).__name__ in (
                   "InsufficientPrivilegeError", "RaiseError"
               ), f"Expected RLS violation, got: {exc_info.value}"


# ===========================================================================
# beacon_durable_memory (L3)
# ===========================================================================

class TestBeaconDurableMemory:
    async def test_insert_and_fetch(self, conn_a):
        row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_durable_memory
                (user_id, key, value, source, confidence)
            VALUES ($1::uuid, 'inferred_preferences/quiet_mornings', 'true',
                    'compaction_weekly', 'high')
            RETURNING id, key, confidence, evidence
            """,
            USER_A,
        )
        assert row["key"] == "inferred_preferences/quiet_mornings"
        assert row["confidence"] == "high"
        assert row["evidence"] is None  # nullable JSONB

    async def test_evidence_jsonb_roundtrip(self, conn_a):
        evidence = [{"dispatch_id": str(uuid.uuid4()), "weight": 0.8}]
        row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_durable_memory
                (user_id, key, value, source, evidence)
            VALUES ($1::uuid, 'historical_summaries/may_2026', 'summary text',
                    'compaction_monthly', $2)
            RETURNING evidence
            """,
            USER_A, evidence,
        )
        assert isinstance(row["evidence"], list)
        assert row["evidence"][0]["weight"] == 0.8

    async def test_rls_user_b_cannot_see_user_a_rows(self, conn_a, conn_b):
        dm_row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_durable_memory
                (user_id, key, value, source)
            VALUES ($1::uuid, 'patterns/overall', 'stable', 'compaction_monthly')
            RETURNING id
            """,
            USER_A,
        )
        dm_id = dm_row["id"]
        row_b = await conn_b.fetchrow(
            "SELECT id FROM beacon_durable_memory WHERE id = $1", dm_id
        )
        assert row_b is None, "RLS failed: user B can see user A's beacon_durable_memory row"


# ===========================================================================
# beacon_compaction_log
# ===========================================================================

class TestBeaconCompactionLog:
    async def test_insert_and_fetch(self, conn_a):
        row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_compaction_log
                (user_id, trigger_type, tokens_before, tokens_after,
                 surfaces_touched, notes)
            VALUES ($1::uuid, 'weekly', 3200, 1800,
                    '{"dispatches": 47, "decisions": 102}'::jsonb,
                    'Routine weekly compaction')
            RETURNING id, trigger_type, tokens_before, tokens_after
            """,
            USER_A,
        )
        assert row["trigger_type"] == "weekly"
        assert row["tokens_before"] == 3200
        assert row["tokens_after"] == 1800

    async def test_rls_user_b_cannot_see_user_a_rows(self, conn_a, conn_b):
        log_row = await conn_a.fetchrow(
            """
            INSERT INTO beacon_compaction_log (user_id, trigger_type)
            VALUES ($1::uuid, 'monthly')
            RETURNING id
            """,
            USER_A,
        )
        log_id = log_row["id"]
        row_b = await conn_b.fetchrow(
            "SELECT id FROM beacon_compaction_log WHERE id = $1", log_id
        )
        assert row_b is None, "RLS failed: user B can see user A's beacon_compaction_log row"


# ===========================================================================
# conversations table extensions
# ===========================================================================

class TestConversationExtensions:
    async def test_handle_column_exists_and_is_nullable(self, conn_a):
        """conversations.handle column exists and accepts NULL."""
        row = await conn_a.fetchrow(
            """
            INSERT INTO conversations (user_id, name, type, priority, state)
            VALUES ($1::uuid, 'Test Conv', 'interactive', 'normal', 'open')
            RETURNING id::text, handle, expires_at
            """,
            USER_A,
        )
        assert row["handle"] is None
        assert row["expires_at"] is None

    async def test_handle_column_accepts_value(self, conn_a):
        row = await conn_a.fetchrow(
            """
            INSERT INTO conversations (user_id, name, type, priority, state, handle)
            VALUES ($1::uuid, 'Morning Prep', 'interactive', 'normal', 'pending', 'morning-prep')
            RETURNING handle, state
            """,
            USER_A,
        )
        assert row["handle"] == "morning-prep"
        assert row["state"] == "pending"

    async def test_state_pending_accepted(self, conn_a):
        row = await conn_a.fetchrow(
            """
            INSERT INTO conversations (user_id, name, state)
            VALUES ($1::uuid, 'Pending Conv', 'pending')
            RETURNING state
            """,
            USER_A,
        )
        assert row["state"] == "pending"

    async def test_state_rejected_accepted(self, conn_a):
        row = await conn_a.fetchrow(
            """
            INSERT INTO conversations (user_id, name, state)
            VALUES ($1::uuid, 'Rejected Conv', 'rejected')
            RETURNING state
            """,
            USER_A,
        )
        assert row["state"] == "rejected"

    async def test_expires_at_accepts_timestamp(self, conn_a):
        row = await conn_a.fetchrow(
            """
            INSERT INTO conversations
                (user_id, name, state, expires_at)
            VALUES ($1::uuid, 'Expiring Conv', 'pending',
                    now() + interval '48 hours')
            RETURNING state, expires_at
            """,
            USER_A,
        )
        assert row["state"] == "pending"
        assert row["expires_at"] is not None

    async def test_handle_unique_per_user(self, conn_a):
        """Two conversations with the same handle for the same user is rejected."""
        await conn_a.execute(
            """
            INSERT INTO conversations (user_id, name, state, handle)
            VALUES ($1::uuid, 'Conv One', 'pending', 'my-handle')
            """,
            USER_A,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn_a.execute(
                """
                INSERT INTO conversations (user_id, name, state, handle)
                VALUES ($1::uuid, 'Conv Two', 'pending', 'my-handle')
                """,
                USER_A,
            )

    async def test_handle_unique_index_is_per_user(self, conn_a, conn_b):
        """Same handle on different users should be fine."""
        await conn_a.execute(
            """
            INSERT INTO conversations (user_id, name, state, handle)
            VALUES ($1::uuid, 'User A Conv', 'pending', 'shared-handle')
            """,
            USER_A,
        )
        # Should not raise for a different user
        await conn_b.execute(
            """
            INSERT INTO conversations (user_id, name, state, handle)
            VALUES ($1::uuid, 'User B Conv', 'pending', 'shared-handle')
            """,
            USER_B,
        )


# ===========================================================================
# Conversation state — Pydantic validation in API layer
# ===========================================================================

class TestConversationStatePydantic:
    """Verify that ConversationPatch accepts all 4 valid state values."""

    def test_patch_accepts_open(self):
        from api.routes.conversations import ConversationPatch
        p = ConversationPatch(state="open")
        assert p.state == "open"

    def test_patch_accepts_closed(self):
        from api.routes.conversations import ConversationPatch
        p = ConversationPatch(state="closed")
        assert p.state == "closed"

    def test_patch_accepts_pending(self):
        from api.routes.conversations import ConversationPatch
        p = ConversationPatch(state="pending")
        assert p.state == "pending"

    def test_patch_accepts_rejected(self):
        from api.routes.conversations import ConversationPatch
        p = ConversationPatch(state="rejected")
        assert p.state == "rejected"

    def test_patch_rejects_invalid_state(self):
        from api.routes.conversations import ConversationPatch
        import pydantic
        with pytest.raises((ValueError, pydantic.ValidationError)):
            ConversationPatch(state="bogus")
