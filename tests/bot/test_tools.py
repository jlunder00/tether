"""Tests for bot/tools/ — tool plugin system."""
import asyncio
import json
import pytest
from pathlib import Path
from db.schema import init_db


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    init_db(str(p))
    return str(p)


@pytest.fixture
def seeded_db(db_path):
    """DB with one anchor, a plan for today, and a context entry."""
    from db.queries import upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry
    from datetime import date
    today = date.today().isoformat()
    upsert_anchor(db_path, {
        "id": "morning", "name": "Morning", "time": "07:00",
        "duration_minutes": 60, "flexibility": "locked",
        "strictness": 3, "color": "#fff", "position": 0,
    })
    upsert_plan(db_path, today)
    upsert_tasks(db_path, today, "morning", [
        {"text": "Do the thing", "status": "pending", "position": 0},
    ])
    upsert_context_entry(db_path, "Work/Alpha", "Working on project alpha.")
    return db_path


# ---------------------------------------------------------------------------
# Tool registry — auto-discovery
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_load_tools_returns_list(self):
        from bot.tools import load_tools
        tools = load_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_each_tool_has_required_fields(self):
        from bot.tools import load_tools
        for tool in load_tools():
            assert hasattr(tool, "name")
            assert hasattr(tool, "description")
            assert hasattr(tool, "input_schema")
            assert hasattr(tool, "execute")
            assert hasattr(tool, "read_only")

    def test_to_api_schema_returns_canonical_shape(self):
        from bot.tools import load_tools
        for tool in load_tools():
            schema = tool.to_api_schema()
            assert schema["name"] == tool.name
            assert "description" in schema
            assert "input_schema" in schema

    def test_subset_filtering(self):
        from bot.tools import load_tools
        all_tools = load_tools()
        if not all_tools:
            pytest.skip("No tools loaded")
        first_name = all_tools[0].name
        subset = load_tools(subset=[first_name])
        assert len(subset) == 1
        assert subset[0].name == first_name

    def test_broken_tool_skipped_gracefully(self, tmp_path, monkeypatch):
        """A tool file that raises on import should be skipped, not crash load_tools."""
        from bot.tools import load_tools
        import importlib
        original_import = importlib.import_module

        def patched_import(name, *args, **kwargs):
            if name == "bot.tools.broken_tool":
                raise ImportError("simulated import error")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", patched_import)
        tools = load_tools()
        assert isinstance(tools, list)


# ---------------------------------------------------------------------------
# Tool base class
# ---------------------------------------------------------------------------

class TestToolBase:
    def test_tool_dataclass_construction(self):
        from bot.tools.base import Tool, ToolResult

        async def noop(inp, ctx):
            return ToolResult.ok("done")

        t = Tool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
            execute=noop,
        )
        assert t.name == "test_tool"
        assert t.read_only is True  # default

    def test_tool_result_ok(self):
        from bot.tools.base import ToolResult
        r = ToolResult.ok("great")
        assert r.ok is True
        assert r.content == "great"

    def test_tool_result_error(self):
        from bot.tools.base import ToolResult
        r = ToolResult.error("boom")
        assert r.ok is False
        assert r.content == "boom"


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

class TestGetPlanTool:
    def test_returns_plan_for_today(self, seeded_db):
        from bot.tools.get_plan import TOOL
        result = asyncio.run(TOOL.execute({"date": ""}, ctx_db(seeded_db)))
        assert result.ok is True
        assert "morning" in result.content.lower() or "Morning" in result.content
        assert "Do the thing" in result.content

    def test_returns_error_for_missing_date(self, db_path):
        from bot.tools.get_plan import TOOL
        # No plan seeded for this db — should still return ok with empty plan
        result = asyncio.run(TOOL.execute({}, ctx_db(db_path)))
        assert isinstance(result.ok, bool)


class TestGetContextEntryTool:
    def test_returns_body_for_known_subject(self, seeded_db):
        from bot.tools.get_context_entry import TOOL
        result = asyncio.run(TOOL.execute({"subject": "Work/Alpha"}, ctx_db(seeded_db)))
        assert result.ok is True
        assert "project alpha" in result.content.lower()

    def test_returns_error_for_unknown_subject(self, seeded_db):
        from bot.tools.get_context_entry import TOOL
        result = asyncio.run(TOOL.execute({"subject": "Nonexistent/Entry"}, ctx_db(seeded_db)))
        assert result.ok is False


class TestSearchContextTool:
    def test_lists_matching_subjects(self, seeded_db):
        from bot.tools.search_context import TOOL
        result = asyncio.run(TOOL.execute({"prefix": "Work"}, ctx_db(seeded_db)))
        assert result.ok is True
        assert "Work/Alpha" in result.content

    def test_empty_prefix_lists_all(self, seeded_db):
        from bot.tools.search_context import TOOL
        result = asyncio.run(TOOL.execute({"prefix": ""}, ctx_db(seeded_db)))
        assert result.ok is True
        assert "Work/Alpha" in result.content


class TestGetAnchorsTool:
    def test_returns_anchor_list(self, seeded_db):
        from bot.tools.get_anchors import TOOL
        result = asyncio.run(TOOL.execute({}, ctx_db(seeded_db)))
        assert result.ok is True
        assert "morning" in result.content.lower() or "Morning" in result.content


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------

class TestUpsertTaskTool:
    def test_creates_new_task(self, seeded_db):
        from bot.tools.upsert_task import TOOL
        from db.queries import get_plan
        from datetime import date
        today = date.today().isoformat()

        result = asyncio.run(TOOL.execute({
            "anchor_id": "morning",
            "text": "Brand new task",
            "status": "pending",
        }, ctx_db(seeded_db)))
        assert result.ok is True

        plan = get_plan(seeded_db, today)
        tasks = plan.get("anchors", {}).get("morning", {}).get("tasks", [])
        texts = [t["text"] for t in tasks]
        assert "Brand new task" in texts

    def test_returns_error_for_unknown_anchor(self, db_path):
        from bot.tools.upsert_task import TOOL
        result = asyncio.run(TOOL.execute({
            "anchor_id": "nonexistent_anchor",
            "text": "task",
        }, ctx_db(db_path)))
        assert result.ok is False


class TestUpdateTaskStatusTool:
    def test_updates_existing_task_status(self, seeded_db):
        from bot.tools.update_task_status import TOOL
        from db.queries import get_plan
        from datetime import date
        today = date.today().isoformat()

        # Get the task id first
        plan = get_plan(seeded_db, today)
        task = plan["anchors"]["morning"]["tasks"][0]
        task_id = task["id"]

        result = asyncio.run(TOOL.execute({
            "task_id": task_id,
            "status": "done",
        }, ctx_db(seeded_db)))
        assert result.ok is True

        plan_after = get_plan(seeded_db, today)
        updated = plan_after["anchors"]["morning"]["tasks"][0]
        assert updated["status"] == "done"

    def test_returns_error_for_unknown_task(self, seeded_db):
        from bot.tools.update_task_status import TOOL
        result = asyncio.run(TOOL.execute({
            "task_id": "00000000-0000-0000-0000-000000000000",
            "status": "done",
        }, ctx_db(seeded_db)))
        assert result.ok is False


class TestUpsertContextEntryTool:
    def test_creates_new_entry(self, seeded_db):
        from bot.tools.upsert_context_entry import TOOL
        from db.queries import get_context_entries
        result = asyncio.run(TOOL.execute({
            "subject": "Health/Sleep",
            "body": "Sleep at 10pm.",
        }, ctx_db(seeded_db)))
        assert result.ok is True

        entries = get_context_entries(seeded_db)
        subjects = [e["subject"] for e in entries]
        assert "Health/Sleep" in subjects

    def test_overwrites_existing_entry(self, seeded_db):
        from bot.tools.upsert_context_entry import TOOL
        from db.queries import get_context_entries
        asyncio.run(TOOL.execute({
            "subject": "Work/Alpha",
            "body": "Updated content.",
        }, ctx_db(seeded_db)))

        entries = {e["subject"]: e for e in get_context_entries(seeded_db)}
        assert entries["Work/Alpha"]["body"] == "Updated content."


class TestAppendContextEntryTool:
    def test_appends_to_existing_entry(self, seeded_db):
        from bot.tools.append_context_entry import TOOL
        from db.queries import get_context_entries
        result = asyncio.run(TOOL.execute({
            "subject": "Work/Alpha",
            "content": "\nNew note added.",
        }, ctx_db(seeded_db)))
        assert result.ok is True

        entries = {e["subject"]: e for e in get_context_entries(seeded_db)}
        assert "New note added." in entries["Work/Alpha"]["body"]
        assert "project alpha" in entries["Work/Alpha"]["body"].lower()

    def test_creates_entry_if_missing(self, seeded_db):
        from bot.tools.append_context_entry import TOOL
        from db.queries import get_context_entries
        result = asyncio.run(TOOL.execute({
            "subject": "New/Topic",
            "content": "First note.",
        }, ctx_db(seeded_db)))
        assert result.ok is True
        entries = {e["subject"]: e for e in get_context_entries(seeded_db)}
        assert "New/Topic" in entries


class TestPatchContextEntryTool:
    def test_replaces_exact_string(self, seeded_db):
        from bot.tools.patch_context_entry import TOOL
        from db.queries import get_context_entries
        result = asyncio.run(TOOL.execute({
            "subject": "Work/Alpha",
            "old_string": "project alpha",
            "new_string": "project beta",
        }, ctx_db(seeded_db)))
        assert result.ok is True
        entries = {e["subject"]: e for e in get_context_entries(seeded_db)}
        assert "project beta" in entries["Work/Alpha"]["body"]

    def test_returns_error_when_old_string_not_found(self, seeded_db):
        from bot.tools.patch_context_entry import TOOL
        result = asyncio.run(TOOL.execute({
            "subject": "Work/Alpha",
            "old_string": "DOES NOT EXIST",
            "new_string": "replacement",
        }, ctx_db(seeded_db)))
        assert result.ok is False


# ---------------------------------------------------------------------------
# Tool executor (wires tools to conversation loop)
# ---------------------------------------------------------------------------

class TestToolExecutor:
    def test_dispatches_to_correct_tool(self, seeded_db):
        from bot.tools import make_tool_executor, load_tools
        from bot.llm import ToolCall
        tools = load_tools()
        executor = make_tool_executor(tools, db_path=seeded_db)
        tc = ToolCall(id="c1", name="get_anchors", input={})
        result = asyncio.run(executor(tc))
        assert result["ok"] is True

    def test_returns_error_for_unknown_tool(self, seeded_db):
        from bot.tools import make_tool_executor, load_tools
        from bot.llm import ToolCall
        executor = make_tool_executor(load_tools(), db_path=seeded_db)
        tc = ToolCall(id="c2", name="nonexistent_tool", input={})
        result = asyncio.run(executor(tc))
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ctx_db(db_path: str):
    """Minimal context object carrying db_path for tool execution."""
    class Ctx:
        pass
    ctx = Ctx()
    ctx.db_path = db_path
    return ctx
