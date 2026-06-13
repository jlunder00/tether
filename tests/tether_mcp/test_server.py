"""Smoke tests for the MCP server — one test per tool, Postgres-backed."""
import pytest
from datetime import date
from tests.tether_mcp.conftest import ANCHOR_ID, TEST_USER_ID


@pytest.fixture
async def seeded(conn):
    from db.pg_queries import upsert_anchor, upsert_plan, upsert_tasks, ensure_node_path, upsert_section
    today = str(date.today())
    await upsert_anchor(conn, {
        "id": ANCHOR_ID, "name": "Grind", "time": "09:00",
        "duration_minutes": 60, "flexibility": "locked",
        "strictness": 4, "color": "#e05c5c", "position": 0,
    })
    await upsert_plan(conn, today)
    tasks = await upsert_tasks(conn, today, ANCHOR_ID, [{"text": "Test task"}], notes="")
    node = await ensure_node_path(conn, "Work/Alpha")
    await upsert_section(conn, node["id"], "details", "Alpha project details.")
    return {"today": today, "task_id": tasks[0]["id"]}


def test_server_imports():
    from tether_mcp.server import mcp
    assert mcp is not None


@pytest.mark.asyncio
async def test_get_plan(seeded):
    from tether_mcp.server import get_plan
    plan = await get_plan(seeded["today"])
    assert "anchors" in plan
    assert ANCHOR_ID in plan["anchors"]


@pytest.mark.asyncio
async def test_get_anchors(seeded):
    from tether_mcp.server import get_anchors
    result = await get_anchors()
    assert "anchors" in result
    assert "current" in result
    assert any(a["id"] == ANCHOR_ID for a in result["anchors"])


@pytest.mark.asyncio
async def test_search(seeded):
    from tether_mcp.server import search
    results = await search("Test task")
    assert any(r.get("text") == "Test task" or r.get("name") == "Test task" for r in results)


@pytest.mark.asyncio
async def test_read_tasks_all(seeded):
    from tether_mcp.server import read_tasks
    result = await read_tasks()
    assert isinstance(result, list)
    assert any(t.get("text") == "Test task" for t in result)


@pytest.mark.asyncio
async def test_read_context_requires_conversation_id(seeded):
    """v2: read_context without conversation_id returns a structured error, not a list."""
    from tether_mcp.server import read_context
    result = await read_context()
    assert isinstance(result, dict), "Expected error dict when conversation_id is absent"
    assert result.get("error") == "conversation_id_required"


@pytest.mark.asyncio
async def test_upsert_tasks_create(conn):
    from tether_mcp.server import upsert_tasks
    result = await upsert_tasks([{"text": "New via server"}])
    assert result[0]["id"]
    assert result[0]["text"] == "New via server"


@pytest.mark.asyncio
async def test_upsert_context_create(conn):
    from tether_mcp.server import upsert_context
    result = await upsert_context([{"name": "ServerTest"}])
    assert result[0]["action"] in ("created", "updated")


@pytest.mark.asyncio
async def test_delete_tasks_tool(conn):
    from tether_mcp.server import upsert_tasks, delete_tasks
    created = await upsert_tasks([{"text": "To delete"}])
    tid = created[0]["id"]
    result = await delete_tasks([{"task_uuid": tid, "delete": True}])
    assert result[0]["action"] == "deleted"


@pytest.mark.asyncio
async def test_delete_context_tool(conn):
    from tether_mcp.server import upsert_context, delete_context
    await upsert_context([{"name": "ToDelete"}])
    result = await delete_context([{"path": "ToDelete", "delete": True}])
    assert result[0]["action"] == "deleted"
