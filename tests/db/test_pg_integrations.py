"""Query-layer tests for db/pg_queries/integrations.py.

Covers get/upsert/delete for user_integrations, get/upsert for
integration_sync_state, and soft-delete of tasks by external id.

All tests roll back via the `conn` fixture from pg_conftest — no
persistent side effects.
"""
import pytest

from db.pg_queries import integrations as q
from tests.db.pg_conftest import conn, TEST_USER_ID  # noqa: F401

PROVIDER = "google_calendar"


# ---------------------------------------------------------------------------
# get_integration — empty → None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_integration_returns_none_when_missing(conn):  # noqa: F811
    """get_integration returns None when no row exists for (user_id, provider)."""
    result = await q.get_integration(conn, TEST_USER_ID, PROVIDER)
    assert result is None


# ---------------------------------------------------------------------------
# upsert_integration — insert path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_integration_inserts_row(conn):  # noqa: F811
    """upsert_integration creates a new row and returns it with an id."""
    row = await q.upsert_integration(
        conn, TEST_USER_ID, PROVIDER,
        access_token="at_abc",
        refresh_token="rt_xyz",
        scopes=["calendar.readonly"],
    )
    assert row["user_id"] == TEST_USER_ID
    assert row["provider"] == PROVIDER
    assert row["access_token"] == "at_abc"
    assert row["refresh_token"] == "rt_xyz"
    assert "calendar.readonly" in row["scopes"]
    assert row["id"] is not None


# ---------------------------------------------------------------------------
# get_integration — after upsert
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_integration_returns_row_after_upsert(conn):  # noqa: F811
    """get_integration returns the row created by upsert_integration."""
    await q.upsert_integration(conn, TEST_USER_ID, PROVIDER, access_token="tok")
    row = await q.get_integration(conn, TEST_USER_ID, PROVIDER)
    assert row is not None
    assert row["access_token"] == "tok"


# ---------------------------------------------------------------------------
# upsert_integration — update path (idempotent on conflict)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_integration_updates_existing_row(conn):  # noqa: F811
    """Second upsert updates the row rather than creating a duplicate."""
    await q.upsert_integration(conn, TEST_USER_ID, PROVIDER, access_token="old_token")
    updated = await q.upsert_integration(
        conn, TEST_USER_ID, PROVIDER, access_token="new_token"
    )
    assert updated["access_token"] == "new_token"

    # Confirm there is exactly one row
    rows = await conn.fetch(
        "SELECT id FROM user_integrations WHERE user_id = $1 AND provider = $2",
        TEST_USER_ID, PROVIDER,
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# upsert_integration — partial update preserves existing fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_integration_preserves_unmentioned_fields(conn):  # noqa: F811
    """Updating only access_token must not wipe refresh_token or scopes."""
    await q.upsert_integration(
        conn, TEST_USER_ID, PROVIDER,
        access_token="at_old",
        refresh_token="rt_keep",
        scopes=["calendar.readonly"],
    )
    updated = await q.upsert_integration(
        conn, TEST_USER_ID, PROVIDER,
        access_token="at_new",
    )
    assert updated["access_token"] == "at_new"
    assert updated["refresh_token"] == "rt_keep"
    assert "calendar.readonly" in updated["scopes"]


# ---------------------------------------------------------------------------
# delete_integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_integration_returns_true_when_row_exists(conn):  # noqa: F811
    """delete_integration returns True and removes the row."""
    await q.upsert_integration(conn, TEST_USER_ID, PROVIDER)
    deleted = await q.delete_integration(conn, TEST_USER_ID, PROVIDER)
    assert deleted is True

    row = await q.get_integration(conn, TEST_USER_ID, PROVIDER)
    assert row is None


@pytest.mark.asyncio
async def test_delete_integration_returns_false_when_missing(conn):  # noqa: F811
    """delete_integration returns False if no row matched."""
    deleted = await q.delete_integration(conn, TEST_USER_ID, PROVIDER)
    assert deleted is False


# ---------------------------------------------------------------------------
# delete_integration cascades to sync_state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_integration_cascades_sync_state(conn):  # noqa: F811
    """Deleting an integration removes its sync_state rows via ON DELETE CASCADE."""
    row = await q.upsert_integration(conn, TEST_USER_ID, PROVIDER)
    integration_id = str(row["id"])

    await q.upsert_sync_state(conn, integration_id, "primary")

    await q.delete_integration(conn, TEST_USER_ID, PROVIDER)

    sync_row = await q.get_sync_state(conn, integration_id, "primary")
    assert sync_row is None


# ---------------------------------------------------------------------------
# upsert_sync_state + get_sync_state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_and_get_sync_state(conn):  # noqa: F811
    """upsert_sync_state inserts a row; get_sync_state retrieves it."""
    row = await q.upsert_integration(conn, TEST_USER_ID, PROVIDER)
    integration_id = str(row["id"])

    sync = await q.upsert_sync_state(
        conn, integration_id, "primary",
        sync_cursor="token_abc",
        watch_channel_id="ch_001",
    )
    assert sync["calendar_id"] == "primary"
    assert sync["sync_cursor"] == "token_abc"
    assert sync["watch_channel_id"] == "ch_001"

    fetched = await q.get_sync_state(conn, integration_id, "primary")
    assert fetched is not None
    assert fetched["sync_cursor"] == "token_abc"


@pytest.mark.asyncio
async def test_get_sync_state_returns_none_when_missing(conn):  # noqa: F811
    """get_sync_state returns None for an unknown (integration_id, calendar_id)."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    result = await q.get_sync_state(conn, fake_id, "primary")
    assert result is None


@pytest.mark.asyncio
async def test_upsert_sync_state_updates_cursor(conn):  # noqa: F811
    """Second upsert with a new sync_cursor updates the existing row."""
    row = await q.upsert_integration(conn, TEST_USER_ID, PROVIDER)
    integration_id = str(row["id"])

    await q.upsert_sync_state(conn, integration_id, "primary", sync_cursor="old")
    updated = await q.upsert_sync_state(conn, integration_id, "primary", sync_cursor="new")
    assert updated["sync_cursor"] == "new"

    # Still only one row
    rows = await conn.fetch(
        "SELECT id FROM integration_sync_state WHERE integration_id = $1 AND calendar_id = $2",
        row["id"], "primary",
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# soft_delete_task_by_external_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_soft_delete_task_sets_source_status(conn):  # noqa: F811
    """soft_delete_task_by_external_id sets source_status='cancelled' on the task."""
    # Insert a synced task
    task_uuid = await conn.fetchval(
        "INSERT INTO tasks (user_id, text, status, source, external_id) "
        "VALUES ($1::uuid, 'gcal event', 'pending', $2, $3) RETURNING uuid",
        TEST_USER_ID, PROVIDER, "evt_001",
    )

    deleted = await q.soft_delete_task_by_external_id(conn, TEST_USER_ID, PROVIDER, "evt_001")
    assert deleted is True

    row = await conn.fetchrow(
        "SELECT source_status FROM tasks WHERE uuid = $1", task_uuid
    )
    assert row["source_status"] == "cancelled"


@pytest.mark.asyncio
async def test_soft_delete_task_returns_false_when_missing(conn):  # noqa: F811
    """soft_delete_task_by_external_id returns False when no matching task exists."""
    deleted = await q.soft_delete_task_by_external_id(
        conn, TEST_USER_ID, PROVIDER, "no_such_event"
    )
    assert deleted is False
