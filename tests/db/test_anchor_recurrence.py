"""DB-level tests for anchor-recurring task expansion (Tasks 1–5 Stream A)."""
from __future__ import annotations
import uuid as _uuid_mod
import pytest

from tests.db.pg_conftest import conn, TEST_USER_ID  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_create_anchor_recurring_master_returns_uuid(conn):
    from db.pg_queries.tasks import create_anchor_recurring_master
    anchor_id = str(_uuid_mod.uuid4())
    master_id = await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id,
        text="Daily stand-up", rrule="RRULE:FREQ=DAILY"
    )
    assert master_id is not None
    row = await conn.fetchrow("SELECT uuid, plan_date, anchor_id, rrule, start_time FROM tasks WHERE uuid=$1::uuid", master_id)
    assert row is not None
    assert row["plan_date"] is None
    assert row["start_time"] is None
    assert str(row["anchor_id"]) == anchor_id
    assert "FREQ=DAILY" in row["rrule"]


async def test_set_task_rrule_converts_to_master(conn):
    from db.pg_queries.tasks import set_task_rrule
    anchor_id = str(_uuid_mod.uuid4())
    plain_id = await conn.fetchval(
        """INSERT INTO tasks (uuid, user_id, anchor_id, plan_date, text, status, position)
           VALUES ($1, $2::uuid, $3::uuid, '2026-05-05', 'Stand-up', 'pending', 0) RETURNING uuid::text""",
        str(_uuid_mod.uuid4()), TEST_USER_ID, anchor_id,
    )
    await set_task_rrule(conn, plain_id, "RRULE:FREQ=WEEKLY;BYDAY=MO")
    row = await conn.fetchrow("SELECT plan_date, rrule FROM tasks WHERE uuid=$1::uuid", plain_id)
    assert row["plan_date"] is None
    assert "FREQ=WEEKLY" in row["rrule"]


async def test_set_task_rrule_none_removes_recurrence(conn):
    from db.pg_queries.tasks import set_task_rrule, create_anchor_recurring_master
    anchor_id = str(_uuid_mod.uuid4())
    master_id = await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id, "Stand-up", "RRULE:FREQ=DAILY"
    )
    await set_task_rrule(conn, master_id, None)
    row = await conn.fetchrow("SELECT rrule FROM tasks WHERE uuid=$1::uuid", master_id)
    assert row["rrule"] is None


async def test_get_plan_includes_anchor_recurring_occurrence(conn):
    from db.pg_queries.tasks import create_anchor_recurring_master
    from db.pg_queries.plans import get_plan, upsert_plan
    anchor_id = str(_uuid_mod.uuid4())
    # Weekly on Monday — 2026-05-04 is a Monday
    await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id, "Weekly stand-up", "RRULE:FREQ=WEEKLY;BYDAY=MO"
    )
    await upsert_plan(conn, "2026-05-04")
    plan = await get_plan(conn, "2026-05-04")
    anchor_tasks = plan["anchors"].get(anchor_id, {}).get("tasks", [])
    assert any(t["text"] == "Weekly stand-up" for t in anchor_tasks), (
        f"Expected anchor_recurring task in plan; got anchor tasks: {anchor_tasks}"
    )


async def test_get_plan_excludes_anchor_recurring_on_non_matching_date(conn):
    from db.pg_queries.tasks import create_anchor_recurring_master
    from db.pg_queries.plans import get_plan, upsert_plan
    anchor_id = str(_uuid_mod.uuid4())
    # Weekly on Monday — 2026-05-05 is a Tuesday
    await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id, "Weekly stand-up", "RRULE:FREQ=WEEKLY;BYDAY=MO"
    )
    await upsert_plan(conn, "2026-05-05")
    plan = await get_plan(conn, "2026-05-05")
    anchor_tasks = plan["anchors"].get(anchor_id, {}).get("tasks", [])
    assert not any(t["text"] == "Weekly stand-up" for t in anchor_tasks)


async def test_get_plan_excludes_anchor_recurring_exdated_occurrence(conn):
    from db.pg_queries.tasks import create_anchor_recurring_master, delete_anchor_occurrence
    from db.pg_queries.plans import get_plan, upsert_plan
    anchor_id = str(_uuid_mod.uuid4())
    master_id = await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id, "Daily stand-up", "RRULE:FREQ=DAILY"
    )
    await upsert_plan(conn, "2026-05-05")
    await delete_anchor_occurrence(conn, master_id, "2026-05-05")
    plan = await get_plan(conn, "2026-05-05")
    anchor_tasks = plan["anchors"].get(anchor_id, {}).get("tasks", [])
    assert not any(t["text"] == "Daily stand-up" for t in anchor_tasks), (
        "Exdated occurrence should be suppressed in get_plan"
    )


async def test_delete_anchor_occurrence_adds_exdate(conn):
    from db.pg_queries.tasks import create_anchor_recurring_master, delete_anchor_occurrence
    anchor_id = str(_uuid_mod.uuid4())
    master_id = await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id, "Stand-up", "RRULE:FREQ=DAILY"
    )
    await delete_anchor_occurrence(conn, master_id, "2026-05-05")
    row = await conn.fetchrow("SELECT exdates FROM tasks WHERE uuid=$1::uuid", master_id)
    exdates = list(row["exdates"] or [])
    assert "2026-05-05" in exdates


async def test_delete_anchor_occurrence_idempotent(conn):
    from db.pg_queries.tasks import create_anchor_recurring_master, delete_anchor_occurrence
    anchor_id = str(_uuid_mod.uuid4())
    master_id = await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id, "Stand-up", "RRULE:FREQ=DAILY"
    )
    await delete_anchor_occurrence(conn, master_id, "2026-05-05")
    await delete_anchor_occurrence(conn, master_id, "2026-05-05")
    row = await conn.fetchrow("SELECT exdates FROM tasks WHERE uuid=$1::uuid", master_id)
    exdates = list(row["exdates"] or [])
    assert exdates.count("2026-05-05") == 1  # not duplicated


async def test_truncate_anchor_series_sets_until(conn):
    from db.pg_queries.tasks import create_anchor_recurring_master, truncate_anchor_series
    anchor_id = str(_uuid_mod.uuid4())
    master_id = await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id, "Stand-up", "RRULE:FREQ=DAILY"
    )
    await truncate_anchor_series(conn, master_id, "2026-05-10")
    row = await conn.fetchrow("SELECT rrule FROM tasks WHERE uuid=$1::uuid", master_id)
    # UNTIL should be 2026-05-09 (day before from_date)
    assert "UNTIL=20260509" in row["rrule"]


async def test_create_anchor_recurring_master_embeds_dtstart(conn):
    """DTSTART should be embedded so FREQ=WEEKLY anchors to the correct weekday.

    Without DTSTART, _anchor_recurring_occurs_on would use target_date as dtstart,
    making every day match its own weekday (FREQ=WEEKLY would behave like FREQ=DAILY).
    """
    from db.pg_queries.tasks import create_anchor_recurring_master
    anchor_id = str(_uuid_mod.uuid4())
    master_id = await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id, "Weekly stand-up", "RRULE:FREQ=WEEKLY"
    )
    row = await conn.fetchrow("SELECT rrule FROM tasks WHERE uuid=$1::uuid", master_id)
    assert "DTSTART" in row["rrule"], (
        "create_anchor_recurring_master must embed DTSTART so bare FREQ=WEEKLY "
        "anchors to the creation weekday, not over-matches every day"
    )
    assert "FREQ=WEEKLY" in row["rrule"]


async def test_set_task_rrule_embeds_dtstart_from_plan_date(conn):
    """set_task_rrule should embed DTSTART from the task's plan_date."""
    from db.pg_queries.tasks import set_task_rrule
    anchor_id = str(_uuid_mod.uuid4())
    # Task scheduled on a Monday (2026-05-04)
    plain_id = await conn.fetchval(
        """INSERT INTO tasks (uuid, user_id, anchor_id, plan_date, text, status, position)
           VALUES ($1, $2::uuid, $3::uuid, '2026-05-04', 'Stand-up', 'pending', 0) RETURNING uuid::text""",
        str(_uuid_mod.uuid4()), TEST_USER_ID, anchor_id,
    )
    await set_task_rrule(conn, plain_id, "RRULE:FREQ=WEEKLY")
    row = await conn.fetchrow("SELECT rrule FROM tasks WHERE uuid=$1::uuid", plain_id)
    # DTSTART should be embedded with the original plan_date
    assert "DTSTART:20260504" in row["rrule"], (
        "set_task_rrule must embed DTSTART from original plan_date to preserve weekday anchor"
    )


async def test_set_task_rrule_bumps_version(conn):
    """set_task_rrule must bump version for stale-read detection."""
    from db.pg_queries.tasks import set_task_rrule
    anchor_id = str(_uuid_mod.uuid4())
    plain_id = await conn.fetchval(
        """INSERT INTO tasks (uuid, user_id, anchor_id, plan_date, text, status, position)
           VALUES ($1, $2::uuid, $3::uuid, '2026-05-05', 'Stand-up', 'pending', 0) RETURNING uuid::text""",
        str(_uuid_mod.uuid4()), TEST_USER_ID, anchor_id,
    )
    v_before = await conn.fetchval("SELECT version FROM tasks WHERE uuid=$1::uuid", plain_id)
    await set_task_rrule(conn, plain_id, "RRULE:FREQ=DAILY")
    v_after = await conn.fetchval("SELECT version FROM tasks WHERE uuid=$1::uuid", plain_id)
    assert v_after > v_before, "set_task_rrule must bump version"
