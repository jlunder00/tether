"""RLS isolation tests.

These tests verify two things:
1. The app's database role is not a superuser (superusers bypass all RLS).
2. Row-level security actually isolates data between users.

Both tests fail when DATABASE_URL connects as a superuser (e.g. POSTGRES_USER=tether
from the Docker image, which grants superuser privileges). They pass only after the
tether_app role is created and DATABASE_URL points to it.
"""
import os
import pytest
import asyncpg

from db.postgres import register_jsonb_codec

USER_A = "00000000-0000-0000-0000-000000000aa1"
USER_B = "00000000-0000-0000-0000-000000000bb2"


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — RLS tests skipped")
    return url


async def _seed_users(url: str) -> None:
    c = await asyncpg.connect(dsn=url)
    try:
        await register_jsonb_codec(c)
        await c.execute(
            "INSERT INTO users (id, username, email, password_hash) "
            "VALUES ($1::uuid, 'rls_user_a', 'rls_a@test.com', 'x') ON CONFLICT DO NOTHING",
            USER_A,
        )
        await c.execute(
            "INSERT INTO users (id, username, email, password_hash) "
            "VALUES ($1::uuid, 'rls_user_b', 'rls_b@test.com', 'x') ON CONFLICT DO NOTHING",
            USER_B,
        )
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_app_db_role_is_not_superuser():
    """The role in DATABASE_URL must not be a superuser.

    Superusers bypass all RLS unconditionally — even FORCE ROW LEVEL SECURITY
    has no effect on them. The app must connect as a non-superuser role.
    """
    url = _db_url()
    c = await asyncpg.connect(dsn=url)
    try:
        row = await c.fetchrow(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        assert row is not None
        assert not row["rolsuper"], (
            f"DATABASE_URL role '{await c.fetchval('SELECT current_user')}' is a superuser — "
            "RLS is bypassed for all queries. Create a non-superuser tether_app role and "
            "update DATABASE_URL to use it."
        )
        assert not row["rolbypassrls"], (
            "DATABASE_URL role has BYPASSRLS attribute — RLS is bypassed. "
            "Revoke BYPASSRLS from the role."
        )
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_rls_isolates_tasks_between_users():
    """User B cannot see User A's tasks via a normal app connection.

    This test inserts a task as User A, then queries tasks as User B.
    With a non-superuser role and RLS enabled, User B must see zero rows.
    With a superuser role, RLS is bypassed and User B sees User A's task.
    """
    url = _db_url()
    await _seed_users(url)

    task_uuid = None
    try:
        # Insert a task as User A — committed so it's visible across connections.
        c = await asyncpg.connect(dsn=url)
        tr_a = c.transaction()
        await tr_a.start()
        try:
            await register_jsonb_codec(c)
            result = await c.fetchval(
                "SELECT set_config('app.current_user_id', $1, true)", USER_A
            )
            assert result == USER_A, f"set_config did not take effect: got {result!r}"
            task_uuid = await c.fetchval(
                "INSERT INTO tasks (user_id, text, status) "
                "VALUES ($1::uuid, 'secret task', 'pending') RETURNING uuid",
                USER_A,
            )
            await tr_a.commit()
        except Exception:
            await tr_a.rollback()
            raise
        finally:
            await c.close()

        # Query tasks as User B — must see nothing
        c = await asyncpg.connect(dsn=url)
        tr = c.transaction()
        await tr.start()
        try:
            await register_jsonb_codec(c)
            result = await c.fetchval(
                "SELECT set_config('app.current_user_id', $1, true)", USER_B
            )
            assert result == USER_B, f"set_config did not take effect: got {result!r}"
            rows = await c.fetch("SELECT uuid FROM tasks WHERE uuid = $1", task_uuid)
            assert len(rows) == 0, (
                "User B can see User A's task — RLS is not enforced. "
                "The database role is likely a superuser that bypasses RLS."
            )
        finally:
            await tr.rollback()
            await c.close()
    finally:
        # Clean up the inserted task so stale rows don't affect reruns.
        if task_uuid is not None:
            cleanup = await asyncpg.connect(dsn=url)
            try:
                await cleanup.execute("DELETE FROM tasks WHERE uuid = $1", task_uuid)
            finally:
                await cleanup.close()
