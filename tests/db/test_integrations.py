"""Tests for the integration data model migration.

Covers:
- user_integrations and integration_sync_state tables exist
- RLS on user_integrations: user A cannot see user B's integrations
- CHECK constraint: task with start_time but no end_time raises error
- Unique constraint: duplicate (user_id, source, external_id) raises error
"""
import os
import uuid
import pytest
import asyncpg

from db.postgres import register_jsonb_codec
from tests.db.pg_conftest import conn, TEST_USER_ID  # noqa: F401


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — Postgres tests skipped")
    return url


USER_A = "00000000-0000-0000-0000-000000000ca1"
USER_B = "00000000-0000-0000-0000-000000000cb2"


async def _seed_users(url: str) -> None:
    c = await asyncpg.connect(dsn=url)
    try:
        await register_jsonb_codec(c)
        for uid, name, email in [
            (USER_A, "int_user_a", "int_a@test.com"),
            (USER_B, "int_user_b", "int_b@test.com"),
        ]:
            await c.execute(
                "INSERT INTO users (id, username, email, password_hash) "
                "VALUES ($1::uuid, $2, $3, 'x') ON CONFLICT DO NOTHING",
                uid, name, email,
            )
    finally:
        await c.close()


# ---------------------------------------------------------------------------
# Schema existence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_integrations_table_exists():
    """user_integrations table was created by the migration."""
    url = _db_url()
    c = await asyncpg.connect(dsn=url)
    try:
        row = await c.fetchrow(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'user_integrations'"
        )
        assert row is not None, "user_integrations table does not exist"
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_integration_sync_state_table_exists():
    """integration_sync_state table was created by the migration."""
    url = _db_url()
    c = await asyncpg.connect(dsn=url)
    try:
        row = await c.fetchrow(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'integration_sync_state'"
        )
        assert row is not None, "integration_sync_state table does not exist"
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_tasks_has_event_columns():
    """tasks table has the new event columns from the migration."""
    url = _db_url()
    c = await asyncpg.connect(dsn=url)
    try:
        rows = await c.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'tasks' AND column_name = ANY($1::text[])",
            ["start_time", "end_time", "source", "external_id", "external_url"],
        )
        found = {r["column_name"] for r in rows}
        missing = {"start_time", "end_time", "source", "external_id", "external_url"} - found
        assert not missing, f"tasks table missing columns: {missing}"
    finally:
        await c.close()


# ---------------------------------------------------------------------------
# RLS on user_integrations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rls_isolates_integrations_between_users():
    """User B cannot see User A's integrations via a normal app connection."""
    url = _db_url()
    await _seed_users(url)

    integration_id = None
    try:
        # Insert integration as User A (committed)
        c = await asyncpg.connect(dsn=url)
        tr = c.transaction()
        await tr.start()
        try:
            await register_jsonb_codec(c)
            await c.execute(
                "SELECT set_config('app.current_user_id', $1, true)", USER_A
            )
            integration_id = await c.fetchval(
                "INSERT INTO user_integrations (user_id, provider) "
                "VALUES ($1::uuid, 'google_calendar') RETURNING id",
                USER_A,
            )
            await tr.commit()
        except Exception:
            await tr.rollback()
            raise
        finally:
            await c.close()

        # Query as User B — must see nothing
        c = await asyncpg.connect(dsn=url)
        tr = c.transaction()
        await tr.start()
        try:
            await register_jsonb_codec(c)
            await c.execute(
                "SELECT set_config('app.current_user_id', $1, true)", USER_B
            )
            rows = await c.fetch(
                "SELECT id FROM user_integrations WHERE id = $1", integration_id
            )
            assert len(rows) == 0, (
                "User B can see User A's integration — RLS is not enforced on user_integrations"
            )
        finally:
            await tr.rollback()
            await c.close()
    finally:
        if integration_id is not None:
            cleanup = await asyncpg.connect(dsn=url)
            try:
                await cleanup.execute(
                    "DELETE FROM user_integrations WHERE id = $1", integration_id
                )
            finally:
                await cleanup.close()


# ---------------------------------------------------------------------------
# CHECK constraint: (start_time IS NULL) = (end_time IS NULL)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_start_without_end_raises(conn):  # noqa: F811
    """Inserting a task with start_time but no end_time violates the CHECK constraint."""
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await conn.execute(
            "INSERT INTO tasks (user_id, text, status, start_time) "
            "VALUES ($1::uuid, 'bad event', 'pending', now())",
            TEST_USER_ID,
        )


@pytest.mark.asyncio
async def test_task_end_without_start_raises(conn):  # noqa: F811
    """Inserting a task with end_time but no start_time violates the CHECK constraint."""
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await conn.execute(
            "INSERT INTO tasks (user_id, text, status, end_time) "
            "VALUES ($1::uuid, 'bad event', 'pending', now())",
            TEST_USER_ID,
        )


@pytest.mark.asyncio
async def test_task_both_times_allowed(conn):  # noqa: F811
    """Inserting a task with both start_time and end_time succeeds."""
    task_uuid = await conn.fetchval(
        "INSERT INTO tasks (user_id, text, status, start_time, end_time) "
        "VALUES ($1::uuid, 'good event', 'pending', now(), now() + interval '1 hour') "
        "RETURNING uuid",
        TEST_USER_ID,
    )
    assert task_uuid is not None


# ---------------------------------------------------------------------------
# Unique constraint: (user_id, source, external_id) WHERE source IS NOT NULL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_unique_external_id_constraint(conn):  # noqa: F811
    """Duplicate (user_id, source, external_id) raises a unique constraint error."""
    ext_id = f"gcal_{uuid.uuid4().hex}"
    await conn.execute(
        "INSERT INTO tasks (user_id, text, status, source, external_id) "
        "VALUES ($1::uuid, 'event 1', 'pending', 'google_calendar', $2)",
        TEST_USER_ID, ext_id,
    )
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await conn.execute(
            "INSERT INTO tasks (user_id, text, status, source, external_id) "
            "VALUES ($1::uuid, 'event 2', 'pending', 'google_calendar', $2)",
            TEST_USER_ID, ext_id,
        )


@pytest.mark.asyncio
async def test_task_null_source_allows_duplicates(conn):  # noqa: F811
    """NULL source is excluded from the unique index — multiple null-source tasks allowed."""
    await conn.execute(
        "INSERT INTO tasks (user_id, text, status, source, external_id) "
        "VALUES ($1::uuid, 'task 1', 'pending', NULL, NULL)",
        TEST_USER_ID,
    )
    await conn.execute(
        "INSERT INTO tasks (user_id, text, status, source, external_id) "
        "VALUES ($1::uuid, 'task 2', 'pending', NULL, NULL)",
        TEST_USER_ID,
    )
