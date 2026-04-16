"""Smoke tests for the 9-tool MCP server."""
import pytest
import os
from pathlib import Path
from db.schema import init_db
from db.queries import upsert_anchor, upsert_plan, upsert_tasks as upsert_tasks_db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    upsert_anchor(path, {"id": "grind_am", "name": "Grind", "time": "09:00",
                          "duration_minutes": 60, "flexibility": "locked",
                          "strictness": 4, "color": "#e05c5c", "position": 0})
    upsert_plan(path, "2026-04-15")
    upsert_tasks_db(path, "2026-04-15", "grind_am", [{"text": "Test task", "status": "pending"}])
    return path


@pytest.fixture(autouse=True)
def set_db_env(db_path):
    os.environ["TETHER_DB_PATH"] = str(db_path)
    yield
    del os.environ["TETHER_DB_PATH"]


def test_server_imports():
    from tether_mcp.server import mcp
    assert mcp is not None


def test_get_plan():
    from tether_mcp.server import get_plan
    plan = get_plan("2026-04-15")
    assert "anchors" in plan


def test_get_anchors():
    from tether_mcp.server import get_anchors
    result = get_anchors()
    assert "anchors" in result
    assert "current" in result
    assert any(a["id"] == "grind_am" for a in result["anchors"])


def test_search():
    from tether_mcp.server import search
    results = search("Test task")
    assert len(results) >= 1


def test_read_tasks_all():
    from tether_mcp.server import read_tasks
    result = read_tasks()
    assert len(result) >= 1


def test_read_context_roots():
    from tether_mcp.server import read_context
    result = read_context()
    assert isinstance(result, list)


def test_upsert_tasks_create():
    from tether_mcp.server import upsert_tasks
    result = upsert_tasks([{"text": "New via server"}])
    assert result[0]["id"]
    assert result[0]["text"] == "New via server"


def test_upsert_context_create():
    from tether_mcp.server import upsert_context
    result = upsert_context([{"name": "ServerTest"}])
    assert result[0]["action"] == "created"


def test_delete_tasks_tool():
    from tether_mcp.server import upsert_tasks, delete_tasks
    created = upsert_tasks([{"text": "To delete"}])
    tid = created[0]["id"]
    result = delete_tasks([{"task_uuid": tid, "delete": True}])
    assert result[0]["action"] == "deleted"


def test_delete_context_tool():
    from tether_mcp.server import upsert_context, delete_context
    upsert_context([{"name": "ToDelete"}])
    result = delete_context([{"path": "ToDelete", "delete": True}])
    assert result[0]["action"] == "deleted"
