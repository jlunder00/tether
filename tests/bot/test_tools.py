"""Tests for bot/tools/ — tool plugin system structure (no DB required)."""
import pytest


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

    def test_broken_tool_skipped_gracefully(self, monkeypatch):
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
