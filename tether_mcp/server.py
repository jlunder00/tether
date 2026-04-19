from __future__ import annotations
import os
from datetime import date as date_type, datetime
from typing import Optional

from mcp.server.fastmcp import FastMCP

import db.postgres as pg

mcp = FastMCP("tether", host="0.0.0.0", port=5001)

_pool: pg.asyncpg.Pool | None = None


async def _get_pool() -> pg.asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await pg.create_pool()
    return _pool


def _get_user_id() -> str | None:
    return os.environ.get("TETHER_USER_ID")


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
async def upsert_tasks(tasks: list[dict]) -> list[dict]:
    """Batch create or update tasks.

    Each spec: {task_uuid?, text, status?, description?, date?, anchor_id?, backlog?,
    context_subject?, node_ids?, node_ids_remove?, milestone_ids?, blocked_by?,
    blocked_by_remove?, subtasks?, subtasks_remove?}.
    Text/description support write modes: bare string=replace, {mode:"append",value:"..."},
    {mode:"patch",operations:[{find,replace}]} or {mode:"patch",operations:[{lines,replace}]}."""
    from tether_mcp.tools.upsert_tasks import execute_upsert_tasks
    pool = await _get_pool()
    async with pg.get_conn(pool, _get_user_id()) as conn:
        return await execute_upsert_tasks(conn, tasks)


@mcp.tool()
async def upsert_context(nodes: list[dict]) -> list[dict]:
    """Batch create or update context nodes/milestones.

    Each spec: {name (slash-path ok), node_id?, node_type?, description?, status?, color?,
    target_date?, parent?, sections?: {type: {filename: body}}, children?: [...]}.
    Section bodies and description support write modes."""
    from tether_mcp.tools.upsert_context import execute_upsert_context
    pool = await _get_pool()
    async with pg.get_conn(pool, _get_user_id()) as conn:
        return await execute_upsert_context(conn, nodes)


@mcp.tool()
async def delete_tasks(operations: list[dict]) -> list[dict]:
    """Delete tasks or clear content within tasks.

    Each op: {task_uuid, delete?, clear_description?, clear_subtasks?, clear_deps?,
    clear_node_links?, clear_context?}. delete=True removes entire task."""
    from tether_mcp.tools.delete_tasks import execute_delete_tasks
    pool = await _get_pool()
    async with pg.get_conn(pool, _get_user_id()) as conn:
        return await execute_delete_tasks(conn, operations)


@mcp.tool()
async def delete_context(operations: list[dict]) -> list[dict]:
    """Delete context nodes or clear content within nodes.

    Each op: {node_id or path, delete?, archive?, clear_sections?, delete_files?,
    clear_description?, clear_task_links?}. delete=True removes entire node+children."""
    from tether_mcp.tools.delete_context import execute_delete_context
    pool = await _get_pool()
    async with pg.get_conn(pool, _get_user_id()) as conn:
        return await execute_delete_context(conn, operations)


@mcp.tool()
async def read_context(
    paths: list[str] = [],
    node_ids: list[str] = [],
    depth: int = 0,
    include_sections: bool = False,
    include_tasks: bool = False,
) -> list:
    """Read context nodes. No params=roots. depth: 0=node only, 1=children, -1=full subtree.
    Section bodies in cat-n format (1-indexed line numbers with tabs)."""
    from tether_mcp.tools.read_context import execute_read_context
    pool = await _get_pool()
    async with pg.get_conn(pool, _get_user_id()) as conn:
        return await execute_read_context(conn, paths, node_ids, depth, include_sections, include_tasks)


@mcp.tool()
async def read_tasks(
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
    pool = await _get_pool()
    async with pg.get_conn(pool, _get_user_id()) as conn:
        return await execute_read_tasks(conn, task_ids, status, context, milestone_id, date, anchor_id, unscheduled, include_deps, include_subtasks)


@mcp.tool()
async def get_plan(date: str = "") -> dict:
    """Get structured daily plan with anchor-grouped tasks. Default=today."""
    from db.pg_queries import get_plan as _get_plan
    d = date or str(date_type.today())
    pool = await _get_pool()
    async with pg.get_conn(pool, _get_user_id()) as conn:
        return await _get_plan(conn, d)


@mcp.tool()
async def get_anchors() -> dict:
    """Get all anchor definitions + currently active anchor."""
    from db.pg_queries import get_anchors as _get_anchors_db
    pool = await _get_pool()
    async with pg.get_conn(pool, _get_user_id()) as conn:
        anchors = await _get_anchors_db(conn)
    current = _current_anchor(anchors) if anchors else None
    return {"anchors": anchors, "current": current}


@mcp.tool()
async def search(query: str, type: str = "all") -> list[dict]:
    """Full-text search across tasks, milestones, context. type: all/task/milestone/context."""
    from db.pg_queries import search_entities
    if not query.strip():
        return []
    pool = await _get_pool()
    async with pg.get_conn(pool, _get_user_id()) as conn:
        return await search_entities(conn, query.strip(), type)


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
