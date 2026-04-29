"""API tests for anchor-recurring task endpoints (PATCH rrule, scope-aware DELETE)."""
from __future__ import annotations
import pytest
from db.pg_queries import upsert_anchor
from db.pg_queries.tasks import create_anchor_recurring_master

ANCHOR_ID = "00000000-0000-0000-0000-000000000020"
ANCHOR = {
    "id": ANCHOR_ID, "name": "Morning Block", "time": "09:00",
    "duration_minutes": 60, "flexibility": "locked",
    "strictness": 4, "color": "#5c8ee0", "position": 0,
}

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def anchor_id(conn):
    await upsert_anchor(conn, ANCHOR)
    return ANCHOR_ID


@pytest.fixture
async def task_id(conn, anchor_id):
    """Plain anchor task (plan_date set, no rrule)."""
    from tests.api.conftest import TEST_USER_ID
    row = await conn.fetchrow(
        """INSERT INTO tasks (uuid, user_id, anchor_id, plan_date, text, status, position)
           VALUES (gen_random_uuid(), $1::uuid, $2::uuid, '2026-05-05', 'Stand-up', 'pending', 0)
           RETURNING uuid""",
        TEST_USER_ID, anchor_id,
    )
    return str(row["uuid"])


@pytest.fixture
async def non_anchor_task_id(conn):
    """Task with no anchor_id."""
    from tests.api.conftest import TEST_USER_ID
    row = await conn.fetchrow(
        """INSERT INTO tasks (uuid, user_id, plan_date, text, status, position)
           VALUES (gen_random_uuid(), $1::uuid, '2026-05-05', 'Standalone', 'pending', 0)
           RETURNING uuid""",
        TEST_USER_ID,
    )
    return str(row["uuid"])


@pytest.fixture
async def master_task_id(conn, anchor_id):
    """Anchor-recurring master (rrule set, plan_date=NULL)."""
    from tests.api.conftest import TEST_USER_ID
    return await create_anchor_recurring_master(
        conn, TEST_USER_ID, anchor_id, "Daily stand-up", "RRULE:FREQ=DAILY"
    )


async def test_set_rrule_on_anchor_task(api_client, anchor_id, task_id):
    resp = await api_client.patch(
        f"/api/tasks/{task_id}/rrule",
        json={"rrule": "RRULE:FREQ=WEEKLY;BYDAY=MO"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "FREQ=WEEKLY" in data["rrule"]


async def test_clear_rrule_on_anchor_task(api_client, anchor_id, task_id):
    await api_client.patch(f"/api/tasks/{task_id}/rrule", json={"rrule": "RRULE:FREQ=DAILY"})
    resp = await api_client.patch(f"/api/tasks/{task_id}/rrule", json={"rrule": None})
    assert resp.status_code == 200
    assert resp.json()["rrule"] is None


async def test_set_rrule_on_non_anchor_task_returns_400(api_client, non_anchor_task_id):
    resp = await api_client.patch(
        f"/api/tasks/{non_anchor_task_id}/rrule",
        json={"rrule": "RRULE:FREQ=DAILY"},
    )
    assert resp.status_code == 400


async def test_delete_anchor_task_scope_this(api_client, anchor_id, master_task_id):
    resp = await api_client.delete(
        f"/api/tasks/{master_task_id}",
        params={"scope": "this", "original_date": "2026-05-05"},
    )
    assert resp.status_code == 204
    # Master should still exist
    check = await api_client.get(f"/api/tasks/{master_task_id}")
    assert check.status_code == 200
    # 2026-05-05 should be excluded
    assert "2026-05-05" in (check.json().get("exdates") or [])


async def test_delete_anchor_task_scope_this_missing_date_returns_422(api_client, anchor_id, master_task_id):
    resp = await api_client.delete(
        f"/api/tasks/{master_task_id}",
        params={"scope": "this"},
    )
    assert resp.status_code == 422


async def test_delete_anchor_task_scope_all_removes_task(api_client, anchor_id, master_task_id):
    resp = await api_client.delete(
        f"/api/tasks/{master_task_id}",
        params={"scope": "all"},
    )
    assert resp.status_code == 204
    check = await api_client.get(f"/api/tasks/{master_task_id}")
    assert check.status_code == 404
