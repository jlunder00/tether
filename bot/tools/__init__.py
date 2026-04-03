"""Tool plugin registry — auto-discovers all TOOL objects in this package."""
import importlib
import logging
from pathlib import Path
from typing import Callable, Awaitable

from bot.tools.base import Tool, ToolResult
from bot.llm import ToolCall

logger = logging.getLogger(__name__)


def load_tools(subset: list[str] | None = None) -> list[Tool]:
    """Load all tools from this package. Failed imports are skipped with a warning."""
    tools = []
    tools_dir = Path(__file__).parent
    for path in sorted(tools_dir.glob("*.py")):
        if path.name in ("__init__.py", "base.py"):
            continue
        module_name = f"bot.tools.{path.stem}"
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "TOOL"):
                tool = mod.TOOL
                if subset is None or tool.name in subset:
                    tools.append(tool)
        except Exception as e:
            logger.warning("Tool %s failed to load: %s", path.stem, e)
    return tools


def make_tool_executor(
    tools: list[Tool],
    db_path: str,
) -> Callable[[ToolCall], Awaitable[dict]]:
    """Return an async callable that dispatches a ToolCall to the right tool."""
    registry = {t.name: t for t in tools}

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.db_path = db_path

    async def executor(tool_call: ToolCall) -> dict:
        tool = registry.get(tool_call.name)
        if tool is None:
            return {"ok": False, "content": f"Unknown tool: {tool_call.name!r}"}
        result: ToolResult = await tool.execute(tool_call.input, ctx)
        return {"ok": result.ok, "content": result.content}

    return executor
