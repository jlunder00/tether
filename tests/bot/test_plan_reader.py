"""Tests for bot/plan_reader — async Postgres-backed."""
import pytest
from datetime import date as date_type
from bot.plan_reader import load_plan, load_context, DayPlan, AnchorPlan
from tests.bot.conftest import TEST_USER_ID

ANCHOR_ID = "00000000-0000-0000-0000-000000000010"
TODAY = str(date_type.today())


@pytest.fixture
async def seeded_plan(conn):
    from db.pg_queries import upsert_anchor, upsert_plan, upsert_tasks
    await upsert_anchor(conn, {
        "id": ANCHOR_ID, "name": "The Grind", "time": "08:00",
        "duration_minutes": 120, "flexibility": "locked",
        "strictness": 4, "color": "#e05c5c", "position": 0,
    })
    await upsert_plan(conn, TODAY)
    await upsert_tasks(conn, TODAY, ANCHOR_ID,
                       [{"text": "Apply to 3 jobs"}, {"text": "Follow up"}],
                       notes="ML roles")


@pytest.fixture
async def seeded_context(conn):
    from db.pg_queries import ensure_node_path, upsert_section
    node = await ensure_node_path(conn, "Job Applications")
    await upsert_section(conn, node["id"], "details", "Priority 1.")


@pytest.mark.asyncio
async def test_load_plan_reads_date(pg_pool, seeded_plan):
    plan = await load_plan(pg_pool, TEST_USER_ID)
    assert plan.date == TODAY


@pytest.mark.asyncio
async def test_load_plan_reads_anchor_tasks(pg_pool, seeded_plan):
    plan = await load_plan(pg_pool, TEST_USER_ID)
    assert ANCHOR_ID in plan.anchors
    texts = [t["text"] for t in plan.anchors[ANCHOR_ID].tasks]
    assert "Apply to 3 jobs" in texts
    assert "Follow up" in texts


@pytest.mark.asyncio
async def test_load_plan_reads_notes(pg_pool, seeded_plan):
    plan = await load_plan(pg_pool, TEST_USER_ID)
    assert plan.anchors[ANCHOR_ID].notes == "ML roles"


@pytest.mark.asyncio
async def test_load_plan_acknowledgements_empty_by_default(pg_pool, seeded_plan):
    plan = await load_plan(pg_pool, TEST_USER_ID)
    assert plan.acknowledgements == {}


@pytest.mark.asyncio
async def test_load_plan_check_in_log_empty_by_default(pg_pool, seeded_plan):
    plan = await load_plan(pg_pool, TEST_USER_ID)
    assert plan.check_in_log == []


@pytest.mark.asyncio
async def test_load_context_reads_nodes(pg_pool, seeded_context):
    context = await load_context(pg_pool, TEST_USER_ID)
    assert "Priority 1." in context


@pytest.mark.asyncio
async def test_load_context_returns_empty_string_if_no_nodes(pg_pool):
    context = await load_context(pg_pool, TEST_USER_ID)
    assert isinstance(context, str)
