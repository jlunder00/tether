"""read_context tool — batched reads with depth traversal, sections (cat -n), tasks,
M-level summary, and source filtering.

read_context is PURE RETRIEVAL. It does not enforce scope or authorization —
PermissionGate (interactive_agent_layer/permissions.py) is the sole enforcer
(design review §5.1); by the time a read_context call reaches this module, the
gate has already judged whether it should happen. This module never refuses a
read and never returns an out_of_scope error dict.

Params:
  conversation_id — OPTIONAL. When present, each read logs a read-credit
                    against it (bookkeeping only, e.g. for write_node_memory's
                    read-before-write check). When absent, reads simply are
                    not credited — retrieval still proceeds normally.
  M               — M-level detail for node data summary.
                    1=title only, 2=one-liner, 3=themes+abstract, 4=full (default: 4).
                    When M < last, returns from node_data_summary if cached;
                    falls back to node_sections at M=4.
  traverse_depth  — Cost bound in tree-edges from current_node: how far the
                    cascade descends before it stops expanding children.
                    Not an authorization boundary — nodes beyond the bound are
                    simply not expanded, no error dicts.
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
    conversation_id: str | None = None,
    user_id: str | None = None,
    traverse_depth: int = 3,
    _cascade_depth: int = 0,
) -> dict:
    """Build the response dict for a single node, optionally with children/sections/tasks.

    _cascade_depth tracks levels descended from the read_context source node;
    when it reaches traverse_depth, _add_children will not recurse further
    (a cost bound, not an authorization boundary).
    """
    from db.pg_queries import get_node, get_sections, get_node_tasks
    from db.pg_queries.node_memory import get_node_summary
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
                        M, source, conversation_id=conversation_id, user_id=user_id,
                        traverse_depth=traverse_depth, _cascade_depth=_cascade_depth,
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

    # Children (recursive)
    if depth != 0:
        await _add_children(
            conn, result, node, depth, include_sections, include_tasks,
            M, source, conversation_id=conversation_id, user_id=user_id,
            traverse_depth=traverse_depth, _cascade_depth=_cascade_depth,
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
    conversation_id: str | None,
    user_id: str | None,
    traverse_depth: int,
    _cascade_depth: int = 0,
) -> None:
    """Fetch children and add them to result['children'].

    Enforces cascade cost gating only: when traverse_depth > 0 and
    _cascade_depth >= traverse_depth, children are not fetched (a cost bound,
    not an authorization boundary — no error dicts are produced).
    """
    from db.pg_queries import get_children
    from db.pg_queries.node_memory import log_node_read

    # Cost-bound cascade gating: stop descending once traverse_depth levels
    # from the read_context source node have been reached.
    if traverse_depth > 0 and _cascade_depth >= traverse_depth:
        return

    children = await get_children(conn, node["id"])
    next_depth = depth - 1 if depth > 0 else -1
    result["children"] = []

    for child in children:
        child_id = str(child["id"]) if not isinstance(child["id"], str) else child["id"]

        # Log read credit for children read during cascade traversal
        if conversation_id:
            try:
                await log_node_read(
                    conn, child_id, M,
                    conversation_id=conversation_id,
                    title=child.get("name"),
                    user_id=user_id,
                )
            except Exception:
                pass

        result["children"].append(
            await _build_node_response(
                conn, child, next_depth, include_sections, include_tasks, M, source,
                conversation_id=conversation_id, user_id=user_id,
                traverse_depth=traverse_depth, _cascade_depth=_cascade_depth + 1,
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
    traverse_depth: int = 3,
    source: str = "sections",
    user_id: str | None = None,
) -> list:
    """Fetch context nodes with optional depth traversal, section content, and linked tasks.

    Pure retrieval — no authorization is performed here (see module docstring).

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
        conversation_id: Current conversation UUID. Optional — when present,
            reads are credit-logged for bookkeeping (e.g. write_node_memory's
            read-before-write check); when absent, retrieval proceeds
            identically, just without logging.
        M: M-level detail for node data (1=title, 2=one-liner, 3=themes, 4=full).
            When M < 4, returns from node_data_summary cache if available;
            falls back to node_sections at M=4.
        traverse_depth: Cascade cost bound — max tree-edges from the source
            node before children stop being expanded. Not an authorization
            boundary.
        source: 'sections' (default, user-authored) | 'memory' (bot-authored) | 'both'.
        user_id: RLS hardening — explicit caller-supplied user_id, bound
            directly on read-credit inserts instead of relying solely on the
            session GUC. Optional, backward compatible.

    Returns:
        List of node dicts. If no paths and no node_ids, returns root nodes.
    """
    from db.pg_queries import get_node, get_node_by_path, get_children
    from db.pg_queries.node_memory import log_node_read

    async def _fetch_and_log(node: dict) -> dict:
        """Log read credit (if conversation context present), build response."""
        node_id = str(node["id"]) if not isinstance(node["id"], str) else node["id"]

        if conversation_id:
            try:
                await log_node_read(
                    conn, node_id, M,
                    conversation_id=conversation_id,
                    title=node.get("name"),
                    user_id=user_id,
                )
            except Exception:
                pass

        return await _build_node_response(
            conn, node, depth, include_sections, include_tasks, M, source,
            conversation_id=conversation_id, user_id=user_id,
            traverse_depth=traverse_depth,
        )

    # No args → return root nodes
    if not paths and not node_ids:
        roots = await get_children(conn, parent_id=None)
        return [await _fetch_and_log(root) for root in roots]

    results = []

    # Resolve paths
    for path in (paths or []):
        node = await get_node_by_path(conn, path, user_id=user_id)
        if node is None:
            results.append(None)
        else:
            results.append(await _fetch_and_log(node))

    # Resolve node_ids
    for nid in (node_ids or []):
        node = await get_node(conn, nid)
        if node is None:
            results.append(None)
        else:
            results.append(await _fetch_and_log(node))

    return results
