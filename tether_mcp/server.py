from __future__ import annotations
import os
from datetime import date as date_type, datetime
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tether", host="0.0.0.0", port=5001)

_CONFIG_DIR = Path(os.environ.get("TETHER_CONFIG_DIR", Path.home() / ".tether-config"))


def _load_secrets() -> dict:
    p = _CONFIG_DIR / "secrets.json"
    if p.exists():
        import json
        return json.loads(p.read_text())
    return {}

_secrets = _load_secrets()


def _db() -> Path:
    env = os.environ.get("TETHER_DB_PATH")
    if env:
        return Path(env)
    user_id = os.environ.get("TETHER_USER_ID") or _secrets.get("TETHER_USER_ID")
    if user_id:
        return _CONFIG_DIR / "users" / f"{user_id}.db"
    return _CONFIG_DIR / "tether.db"


def _current_anchor(anchors: list[dict], now: Optional[datetime] = None) -> dict:
    if now is None:
        now = datetime.now()
    today = now.date()
    def anchor_start(a: dict) -> datetime:
        h, m = map(int, a["time"].split(":"))
        return datetime(today.year, today.month, today.day, h, m)
    active = anchors[0]
    for anchor in anchors:
        if now >= anchor_start(anchor):
            active = anchor
        else:
            break
    return active


# ─── 9 Consolidated MCP Tools ───────────────────────────────────────────────

@mcp.tool()
def upsert_tasks(tasks: list[dict]) -> list[dict]:
    """Batch create or update tasks.

    Each spec: {task_uuid?, text, status?, description?, date?, anchor_id?, backlog?,
    context_subject?, node_ids?, node_ids_remove?, milestone_ids?, blocked_by?,
    blocked_by_remove?, subtasks?, subtasks_remove?}.
    Text/description support write modes: bare string=replace, {mode:"append",value:"..."},
    {mode:"patch",operations:[{find,replace}]} or {mode:"patch",operations:[{lines,replace}]}."""
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    return execute_upsert_tasks(tasks)


@mcp.tool()
def upsert_context(nodes: list[dict]) -> list[dict]:
    """Batch create or update context nodes/milestones.

    Each spec: {name (slash-path ok), node_id?, node_type?, description?, status?, color?,
    target_date?, parent?, sections?: {type: {filename: body}}, children?: [...]}.
    Section bodies and description support write modes."""
    from tether_mcp.tools.upsert_context import execute_upsert_context
    return execute_upsert_context(nodes)


@mcp.tool()
def delete_tasks(operations: list[dict]) -> list[dict]:
    """Delete tasks or clear content within tasks.

    Each op: {task_uuid, delete?, clear_description?, clear_subtasks?, clear_deps?,
    clear_node_links?, clear_context?}. delete=True removes entire task."""
    from tether_mcp.tools.delete_tasks import execute_delete_tasks
    return execute_delete_tasks(operations)


@mcp.tool()
def delete_context(operations: list[dict]) -> list[dict]:
    """Delete context nodes or clear content within nodes.

    Each op: {node_id or path, delete?, archive?, clear_sections?, delete_files?,
    clear_description?, clear_task_links?}. delete=True removes entire node+children."""
    from tether_mcp.tools.delete_context import execute_delete_context
    return execute_delete_context(operations)


@mcp.tool()
def read_context(
    paths: list[str] = [],
    node_ids: list[str] = [],
    depth: int = 0,
    include_sections: bool = False,
    include_tasks: bool = False,
) -> list:
    """Read context nodes. No params=roots. depth: 0=node only, 1=children, -1=full subtree.
    Section bodies in cat-n format (1-indexed line numbers with tabs)."""
    from tether_mcp.tools.read_context import execute_read_context
    return execute_read_context(paths, node_ids, depth, include_sections, include_tasks)


@mcp.tool()
def read_tasks(
    task_ids: list[str] = [],
    status: str = "",
    context: str = "",
    milestone_id: str = "",
    date: str = "",
    anchor_id: str = "",
    unscheduled: bool = False,
    include_deps: bool = False,
    include_subtasks: bool = False,
) -> list[dict]:
    """Read tasks with filters (AND'd). No filters=all tasks. include_deps/include_subtasks expand."""
    from tether_mcp.tools.read_tasks import execute_read_tasks
    return execute_read_tasks(task_ids, status, context, milestone_id, date, anchor_id, unscheduled, include_deps, include_subtasks)


@mcp.tool()
def get_plan(date: str = "") -> dict:
    """Get structured daily plan with anchor-grouped tasks. Default=today."""
    from db.queries import get_plan as _get_plan
    d = date or str(date_type.today())
    return _get_plan(_db(), d)


@mcp.tool()
def get_anchors() -> dict:
    """Get all anchor definitions + currently active anchor."""
    from db.queries import get_anchors as _get_anchors_db
    anchors = _get_anchors_db(_db())
    current = _current_anchor(anchors) if anchors else None
    return {"anchors": anchors, "current": current}


@mcp.tool()
def search(query: str, type: str = "all") -> list[dict]:
    """Full-text search across tasks, milestones, context. type: all/task/milestone/context."""
    from db.queries import search_entities
    if not query.strip():
        return []
    return search_entities(_db(), query.strip(), type)


# ─── Premium Plugin Hook ────────────────────────────────────────────────────
# If tether-premium is installed, register additional tools (session_done, RAG, analytics).
try:
    from tether_premium.register import register_mcp_tools
    register_mcp_tools(mcp)
except ImportError:
    pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sse", action="store_true", help="Run as SSE server (for network access)")
    args = parser.parse_args()
    mcp.run(transport="sse" if args.sse else "stdio")
