from __future__ import annotations
from datetime import date as date_type, datetime
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import FastMCP

import db.postgres as pg
from tether_mcp.auth import get_user_id, TetherAPIKeyMiddleware

mcp = FastMCP("tether", host="0.0.0.0", port=5001)

_pool: pg.asyncpg.Pool | None = None


async def _get_pool() -> pg.asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await pg.create_pool()
    return _pool


def _resolve_tz(tz_str: str) -> tuple[ZoneInfo, str]:
    """Resolve an IANA timezone string to (ZoneInfo, canonical_name).

    Falls back to UTC when the string is empty or invalid — LLM-provided
    values may be malformed and we must never raise here.
    """
    utc = ZoneInfo("UTC")
    if not tz_str:
        return utc, "UTC"
    try:
        return ZoneInfo(tz_str), tz_str
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return utc, "UTC"


def _current_anchor(anchors: list[dict], now: Optional[datetime] = None) -> dict:
    if now is None:
        now = datetime.now()
    today = now.date()

    def anchor_start(a: dict) -> datetime:
        h, m = map(int, a["time"].split(":"))
        dt = datetime(today.year, today.month, today.day, h, m)
        # When now is timezone-aware, build an aware anchor_start in the same zone
        # so the >= comparison doesn't raise TypeError.
        if now.tzinfo is not None:
            dt = dt.replace(tzinfo=now.tzinfo)
        return dt

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
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_upsert_tasks(conn, tasks)


@mcp.tool()
async def upsert_context(nodes: list[dict]) -> list[dict]:
    """Batch create or update context nodes/milestones.

    Each spec: {name (slash-path ok), node_id?, node_type?, description?, status?, color?,
    target_date?, parent?, sections?: {type: {filename: body}}, children?: [...]}.
    Section bodies and description support write modes."""
    from tether_mcp.tools.upsert_context import execute_upsert_context
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_upsert_context(conn, nodes)


@mcp.tool()
async def delete_tasks(operations: list[dict]) -> list[dict]:
    """Delete tasks or clear content within tasks.

    Each op: {task_uuid, delete?, clear_description?, clear_subtasks?, clear_deps?,
    clear_node_links?, clear_context?}. delete=True removes entire task."""
    from tether_mcp.tools.delete_tasks import execute_delete_tasks
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_delete_tasks(conn, operations)


@mcp.tool()
async def delete_context(operations: list[dict]) -> list[dict]:
    """Delete context nodes or clear content within nodes.

    Each op: {node_id or path, delete?, archive?, clear_sections?, delete_files?,
    clear_description?, clear_task_links?}. delete=True removes entire node+children."""
    from tether_mcp.tools.delete_context import execute_delete_context
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_delete_context(conn, operations)


@mcp.tool()
async def read_context(
    paths: list[str] = [],
    node_ids: list[str] = [],
    depth: int = 0,
    include_sections: bool = False,
    include_tasks: bool = False,
    conversation_id: str = "",
    M: int = 4,
    N: int = 3,
    source: str = "sections",
) -> list:
    """Read context nodes. No params=roots. depth: 0=node only, 1=children, -1=full subtree.
    Section bodies in cat-n format (1-indexed line numbers with tabs).

    conversation_id: Current conversation UUID. REQUIRED (v2) — returns
        {error: 'conversation_id_required'} if absent.
    M: Detail level for node data summary (1=title, 2=one-liner, 3=themes, 4=full sections).
    N: Scope envelope — max tree-edges from conversation's context node. Nodes outside
        N edges return {error: 'out_of_scope', target: ...} instead of data.
    source: 'sections' (user-authored, default) | 'memory' (bot-authored) | 'both'.
    """
    from tether_mcp.tools.read_context import execute_read_context
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_read_context(
            conn, paths, node_ids, depth, include_sections, include_tasks,
            conversation_id=conversation_id or None,
            M=M, N=N, source=source,
        )


@mcp.tool()
async def read_memory(
    scope: str = "user",
    key: str = "",
    prefix: str = "",
    M: int = 2,
) -> dict:
    """Read user memory (L2 or L3) at a given detail level.

    scope: 'user' (L2 working memory) | 'user_durable' (L3 compacted patterns).
    key:    Exact key for a single-entry lookup (returns full value).
    prefix: Filter by key prefix, e.g. 'preferences/'.
    M:      1=keys only, 2=key+preview (default), 3=key+truncated, 4=full value.
    """
    from tether_mcp.tools.read_memory import execute_read_memory
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_read_memory(
            conn,
            scope=scope,
            key=key or None,
            prefix=prefix or None,
            M=M,
        )


@mcp.tool()
async def read_node_memory(
    node_id: str,
    title: str = "",
    M: int = 4,
    conversation_id: str = "",
) -> dict:
    """Read bot-authored notes (origin='conversation_agent') on a context node.

    node_id:         UUID of the context node.
    title:           Optional section name filter.
    M:               1=names only, 2=preview, 3=truncated, 4=full (default).
    conversation_id: Current conversation UUID (for read-credit logging).
    """
    from tether_mcp.tools.read_node_memory import execute_read_node_memory
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_read_node_memory(
            conn,
            node_id=node_id,
            title=title or None,
            M=M,
            conversation_id=conversation_id or None,
        )


@mcp.tool()
async def write_node_memory(
    node_id: str,
    title: str,
    data_type: str,
    value: str,
    mode: str = "additive",
    conversation_id: str = "",
    visible_to_user: bool = True,
) -> dict:
    """Write bot-authored notes to a context node section.

    node_id:         UUID of the context node to write to.
    title:           Section name (key within the node).
    data_type:       Content type hint: 'text' | 'list' | 'json' | 'file'.
    value:           Content to write.
    mode:            'additive' (append) | 'edit' (replace) | 'delete'.
    conversation_id: Current conversation UUID. REQUIRED (v2) — returns
                     {error: 'conversation_id_required'} if absent.
    visible_to_user: False hides this section from user-facing reads.

    Enforcement (v2): conversation_id is required and a prior read_node_memory
    call for this node in the same conversation must exist in node_read_log.
    Returns {error: 'read_before_write_required'} if the read has not occurred.
    """
    from tether_mcp.tools.write_node_memory import execute_write_node_memory
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_write_node_memory(
            conn,
            node_id=node_id,
            title=title,
            data_type=data_type,
            value=value,
            mode=mode,
            conversation_id=conversation_id or None,
            visible_to_user=visible_to_user,
        )


@mcp.tool()
async def propose_user_memory_write(
    key: str,
    value: str,
    reason: str,
    conversation_id: str = "",
) -> dict:
    """Stage a user_memory write proposal for Beacon review.

    key:             Memory key, e.g. 'preferences/morning_routine'.
    value:           Value to write.
    reason:          Why this write is proposed (used by Beacon evaluator to decide).
    conversation_id: Current conversation UUID (linked to the proposal).

    The write is NOT committed immediately. Beacon evaluates after the conversation
    concludes and auto-accepts user-invoked proposals.
    """
    from tether_mcp.tools.propose_user_memory_write import execute_propose_user_memory_write
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_propose_user_memory_write(
            conn,
            key=key,
            value=value,
            reason=reason,
            conversation_id=conversation_id or None,
        )


@mcp.tool()
async def search_context(
    query: str,
    scope: str = "user",
    limit: int = 5,
) -> dict:
    """Semantic search over context nodes (v1 stub — returns empty, API is final).

    query: Natural language search query.
    scope: 'user' (all user nodes) or a node path prefix.
    limit: Max results (1-20).
    """
    from tether_mcp.tools.search_context import execute_search_context
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_search_context(conn, query=query, scope=scope, limit=limit)


@mcp.tool()
async def search_memory(
    query: str,
    scope: str = "user",
    tier: str = "both",
    limit: int = 5,
) -> dict:
    """Semantic search over user memory (v1 stub — returns empty, API is final).

    query: Natural language search query.
    scope: 'user' (default).
    tier:  'l2' | 'l3' | 'both'.
    limit: Max results (1-20).
    """
    from tether_mcp.tools.search_memory import execute_search_memory
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_search_memory(
            conn, query=query, scope=scope, tier=tier, limit=limit
        )


@mcp.tool()
async def grep_context(
    pattern: str,
    scope: str = "user",
    paths: list[str] = [],
    limit: int = 20,
) -> dict:
    """Text search (ILIKE) over node section bodies.

    pattern: Search string. Plain text wraps in % automatically; use % for custom wildcards.
    scope:   'user' (RLS-enforced user nodes only).
    paths:   Optional node paths to restrict search to their subtrees.
    limit:   Max results (default 20, max 100).
    """
    from tether_mcp.tools.grep_context import execute_grep_context
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_grep_context(
            conn,
            pattern=pattern,
            scope=scope,
            paths=paths or None,
            limit=limit,
        )


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
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await execute_read_tasks(conn, task_ids, status, context, milestone_id, date, anchor_id, unscheduled, include_deps, include_subtasks)


@mcp.tool()
async def get_plan(date: str = "", client_timezone: str = "") -> dict:
    """Get structured daily plan with anchor-grouped tasks. Default=today.

    client_timezone: IANA timezone string (e.g. 'America/Los_Angeles').
    When provided and date is omitted, the plan date is resolved using the
    client's local date rather than the server's (UTC) date.
    """
    from db.pg_queries import get_plan as _get_plan
    if date:
        d = date
    elif client_timezone:
        tz, _ = _resolve_tz(client_timezone)
        d = str(datetime.now(tz).date())
    else:
        d = str(date_type.today())
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        return await _get_plan(conn, d)


@mcp.tool()
async def get_anchors(client_timezone: str = "") -> dict:
    """Get all anchor definitions + currently active anchor.

    client_timezone: IANA timezone string (e.g. 'America/Los_Angeles').
    When provided, the active anchor is determined using the client's local
    time. Falls back to UTC when absent or invalid — the response always
    includes a timezone_used field indicating which zone was applied.

    Each anchor in the anchors list includes an is_current: bool field.
    The top-level current field holds the active anchor (back-compat).
    """
    from db.pg_queries import get_anchors as _get_anchors_db
    tz, tz_name = _resolve_tz(client_timezone)
    now = datetime.now(tz)

    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
        anchors = await _get_anchors_db(conn)

    current = _current_anchor(anchors, now=now) if anchors else None

    # Annotate each anchor with is_current and return enriched copies so the
    # original dicts fetched from DB are not mutated.
    current_id = current["anchor_id"] if current else None
    anchors_out = [
        {**a, "is_current": (a["anchor_id"] == current_id)}
        for a in anchors
    ]

    return {"anchors": anchors_out, "current": current, "timezone_used": tz_name}


@mcp.tool()
async def search(query: str, type: str = "all") -> list[dict]:
    """Full-text search across tasks, milestones, context. type: all/task/milestone/context."""
    from db.pg_queries import search_entities
    if not query.strip():
        return []
    pool = await _get_pool()
    async with pg.get_conn(pool, get_user_id()) as conn:
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

    if args.sse:
        import uvicorn
        starlette_app = mcp.sse_app()
        authed_app = TetherAPIKeyMiddleware(starlette_app, _get_pool)
        uvicorn.run(authed_app, host="0.0.0.0", port=5001)
    else:
        mcp.run(transport="stdio")
