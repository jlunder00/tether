"""read_context tool — batched reads with depth traversal, sections (cat -n), tasks,
M-level summary, scope envelope enforcement, and source filtering.

Params added/hardened in memory-context v2:
  conversation_id — REQUIRED (v2). Returns {error: 'conversation_id_required'} if absent.
                    Enables N scope envelope enforcement.
  M               — M-level detail for node data summary.
                    1=title only, 2=one-liner, 3=themes+abstract, 4=full (default: 4).
                    When M < last, returns from node_data_summary if cached;
                    falls back to node_sections at M=4.
  N               — Scope envelope in tree-edges from current_node.
                    Requests outside N edges return {error: 'out_of_scope'}.
                    Note: children returned during depth traversal are also scope-checked;
                    out-of-scope children are replaced with {error: 'out_of_scope', ...}.
  source          — 'sections' | 'memory' | 'both' (default: 'sections').
                    'sections': return user-authored sections (origin='user').
                    'memory':   return bot-authored sections (origin='conversation_agent').
                    'both':     return all sections regardless of origin.

All SQL lives in db/pg_queries/.
"""
from __future__ import annotations

import logging
import asyncpg

logger = logging.getLogger(__name__)


async def _build_node_response(
    conn: asyncpg.Connection,
    node: dict,
    depth: int,
    include_sections: bool,
    include_tasks: bool,
    M: int = 4,
    source: str = "sections",
    *,
    current_node_id: str | None = None,
    N: int = 3,
    conversation_id: str | None = None,
    _cascade_depth: int = 0,
) -> dict:
    """Build the response dict for a single node, optionally with children/sections/tasks.

    When current_node_id is set, each child is scope-checked against N edges.
    Out-of-scope children are represented as {error: 'out_of_scope', target: id}.
    _cascade_depth tracks levels descended from the read_context source node;
    when it reaches N, _add_children will not recurse further.
    """
    from db.pg_queries import get_node, get_children, get_sections, get_node_tasks
    from db.pg_queries.node_memory import get_node_summary, log_node_read, get_node_tree_distance
    from tether_mcp.write_modes import format_cat_n, line_count

    # Ensure we have full node dict (with section_types and children_count)
    if "section_types" not in node or "children_count" not in node:
        full = await get_node(conn, node["id"])
        if full is None:
            return node
        node = full

    result = dict(node)

    # M-level summary (if M < 4, try node_data_summary first)
    if M < 4:
        summary = await get_node_summary(conn, node["id"], M)
        if summary:
            result["summary"] = {
                "M": M,
                "level_ordinal": summary["level_ordinal"],
                "value": summary["value"],
                "abstract": summary.get("abstract"),
                "generated_at": summary.get("generated_at"),
            }
            # With a cached summary and no explicit section request, skip full section load
            if not include_sections:
                if depth != 0:
                    await _add_children(
                        conn, result, node, depth, include_sections, include_tasks,
                        M, source, current_node_id=current_node_id, N=N,
                        conversation_id=conversation_id,
                        _cascade_depth=_cascade_depth,
                    )
                return result

    # Sections (full M=4 or fallback when no summary cached)
    if include_sections:
        all_sections = await get_sections(conn, node["id"])
        grouped: dict[str, list[dict]] = {}
        for s in all_sections:
            # Source filter
            if source == "memory" and s.get("origin") != "conversation_agent":
                continue
            if source == "sections" and s.get("origin") == "conversation_agent":
                continue
            # 'both' passes all

            st = s["section_type"]
            if st not in grouped:
                grouped[st] = []
            body = s["body"] or ""
            grouped[st].append({
                "name": s["name"],
                "body": format_cat_n(body),
                "line_count": line_count(body),
                "origin": s.get("origin", "user"),
                "visible_to_user": s.get("visible_to_user", True),
            })
        result["sections"] = grouped

    # Tasks
    if include_tasks:
        result["tasks"] = await get_node_tasks(conn, node["id"])

    # Children (recursive, with per-child scope check)
    if depth != 0:
        await _add_children(
            conn, result, node, depth, include_sections, include_tasks,
            M, source, current_node_id=current_node_id, N=N,
            conversation_id=conversation_id,
            _cascade_depth=_cascade_depth,
        )

    return result


async def _add_children(
    conn: asyncpg.Connection,
    result: dict,
    node: dict,
    depth: int,
    include_sections: bool,
    include_tasks: bool,
    M: int,
    source: str,
    *,
    current_node_id: str | None,
    N: int,
    conversation_id: str | None,
    _cascade_depth: int = 0,
) -> None:
    """Fetch children and add them to result['children'], applying per-child scope check.

    Enforces M-level cascade depth gating: when N > 0 and _cascade_depth >= N,
    children are not fetched (the current node is at the scope boundary).
    """
    from db.pg_queries import get_children
    from db.pg_queries.node_memory import get_node_tree_distance, log_node_read

    # M-level cascade gating: stop descending when we've reached N levels from source
    if N > 0 and _cascade_depth >= N:
        return

    children = await get_children(conn, node["id"])
    next_depth = depth - 1 if depth > 0 else -1
    result["children"] = []

    for child in children:
        child_id = str(child["id"]) if not isinstance(child["id"], str) else child["id"]

        # Scope check each child independently
        if current_node_id and N > 0:
            dist = await get_node_tree_distance(conn, current_node_id, child_id, N)
            if dist is None:
                result["children"].append({
                    "error": "out_of_scope",
                    "target": child_id,
                    "message": (
                        f"Node {child_id} is more than {N} tree-edges from "
                        f"conversation context node {current_node_id}."
                    ),
                })
                continue

        # Log read credit for in-scope children
        if conversation_id:
            try:
                await log_node_read(
                    conn, child_id, M,
                    conversation_id=conversation_id,
                    title=child.get("name"),
                )
            except Exception:
                pass

        result["children"].append(
            await _build_node_response(
                conn, child, next_depth, include_sections, include_tasks, M, source,
                current_node_id=current_node_id, N=N, conversation_id=conversation_id,
                _cascade_depth=_cascade_depth + 1,
            )
        )


async def execute_read_context(
    conn: asyncpg.Connection,
    paths=None,
    node_ids=None,
    depth: int = 0,
    include_sections: bool = False,
    include_tasks: bool = False,
    conversation_id: str | None = None,
    M: int = 4,
    N: int = 3,
    source: str = "sections",
) -> list | dict:
    """Fetch context nodes with optional depth traversal, section content, and linked tasks.

    Args:
        conn: asyncpg connection (user-scoped via RLS).
        paths: List of slash-separated paths like ["Projects/Tether"]. Resolved to nodes.
        node_ids: List of node IDs to fetch directly.
        depth: How deep to traverse children.
            0  = node only (no children key)
            >0 = include children up to that many levels
            -1 = full subtree (unlimited)
        include_sections: If True, add "sections" dict grouped by section_type.
            Each section entry has {name, body (cat-n format), line_count, origin}.
        include_tasks: If True, add "tasks" list from get_node_tasks.
        conversation_id: Current conversation UUID. Required (v2) — returns
            {error: 'conversation_id_required'} if absent.
        M: M-level detail for node data (1=title, 2=one-liner, 3=themes, 4=full).
            When M < 4, returns from node_data_summary cache if available;
            falls back to node_sections at M=4.
        N: Scope envelope — max tree-edges from conversation's current_node.
            Requests outside N edges return {error: 'out_of_scope', ...}.
            Children during depth traversal are also scope-checked.
        source: 'sections' (default, user-authored) | 'memory' (bot-authored) | 'both'.

    Returns:
        List of node dicts (or error dicts for out-of-scope entries).
        If no paths and no node_ids, returns root nodes.
        {error: 'conversation_id_required', message: str} if conversation_id is absent.
    """
    from db.pg_queries import get_node, get_node_by_path, get_children
    from db.pg_queries.node_memory import (
        log_node_read,
        get_context_node_id_for_conversation,
        get_node_tree_distance,
    )

    # v2: conversation_id is required
    if not conversation_id:
        return {
            "error": "conversation_id_required",
            "message": "conversation_id is required for read_context in v2.",
        }

    # Resolve conversation scope (current_node_id may be None if conversation is unlinked)
    current_node_id = await get_context_node_id_for_conversation(conn, conversation_id)

    async def _fetch_and_check(node: dict) -> dict:
        """Apply scope check, log read, build response."""
        node_id = str(node["id"]) if not isinstance(node["id"], str) else node["id"]

        # Scope envelope check for the top-level requested node
        if current_node_id and N > 0:
            dist = await get_node_tree_distance(conn, current_node_id, node_id, N)
            if dist is None:
                return {
                    "error": "out_of_scope",
                    "target": node_id,
                    "message": (
                        f"Node {node_id} is more than {N} tree-edges from "
                        f"conversation context node {current_node_id}. "
                        "Request permission via the conversation to access it."
                    ),
                }

        # Log read credit for the top-level node
        if conversation_id:
            try:
                await log_node_read(
                    conn, node_id, M,
                    conversation_id=conversation_id,
                    title=node.get("name"),
                )
            except Exception:
                pass

        return await _build_node_response(
            conn, node, depth, include_sections, include_tasks, M, source,
            current_node_id=current_node_id, N=N, conversation_id=conversation_id,
        )

    # No args → return root nodes
    if not paths and not node_ids:
        roots = await get_children(conn, parent_id=None)
        return [await _fetch_and_check(root) for root in roots]

    results = []

    # Resolve paths
    for path in (paths or []):
        node = await get_node_by_path(conn, path)
        if node is None:
            results.append(None)
        else:
            results.append(await _fetch_and_check(node))

    # Resolve node_ids
    for nid in (node_ids or []):
        node = await get_node(conn, nid)
        if node is None:
            results.append(None)
        else:
            results.append(await _fetch_and_check(node))

    return results
