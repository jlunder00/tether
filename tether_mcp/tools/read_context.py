"""read_context tool — batched reads with depth traversal, sections (cat -n), tasks,
M-level summary, scope envelope enforcement, and source filtering.

New params added in memory-context v2:
  conversation_id — when provided, enables N scope envelope enforcement.
                    Optional (legacy callers without it get unscoped reads with a warning).
                    Required for scope-envelope; v2 will make this mandatory.
  M               — M-level detail for node data summary.
                    1=title only, 2=one-liner, 3=themes+abstract, 4=full (default: 4).
                    When M < last, returns from node_data_summary if cached;
                    falls back to node_sections at M=4 (no descent gating in v1).
  N               — Scope envelope in tree-edges from current_node.
                    Requests outside N edges are rejected with {error: 'out_of_scope'}.
                    Only enforced when conversation_id is provided.
  source          — 'sections' | 'memory' | 'both' (default: 'sections').
                    'sections': return node_sections content (existing behavior).
                    'memory':   return bot-authored sections (origin='conversation_agent').
                    'both':     return all sections regardless of origin.
"""
from __future__ import annotations

import logging
import asyncpg

logger = logging.getLogger(__name__)


async def _tree_distance(
    conn: asyncpg.Connection,
    from_id: str,
    to_id: str,
    max_N: int,
) -> int | None:
    """Return the tree distance (edges) between two nodes in the context tree.

    Returns None if the nodes are not connected within max_N edges.
    Uses a recursive CTE that walks both ancestors and descendants.

    O(max_N) queries worth of work — kept bounded by max_N.
    """
    if from_id == to_id:
        return 0

    import uuid as _uuid

    # Walk up to max_N edges in either direction via recursive CTE.
    # We anchor on from_id and expand both parent and child edges.
    row = await conn.fetchrow(
        """
        WITH RECURSIVE reachable(node_id, dist) AS (
            SELECT $1::uuid, 0
          UNION ALL
            SELECT
              CASE WHEN cn.parent_id = r.node_id THEN cn.id
                   ELSE cn.parent_id
              END,
              r.dist + 1
            FROM reachable r
            JOIN context_nodes cn
              ON (cn.id = r.node_id AND cn.parent_id IS NOT NULL)
              OR (cn.parent_id = r.node_id)
            WHERE r.dist < $3
        )
        SELECT dist FROM reachable WHERE node_id = $2::uuid LIMIT 1
        """,
        _uuid.UUID(from_id), _uuid.UUID(to_id), max_N,
    )
    return row["dist"] if row else None


async def _build_node_response(
    conn: asyncpg.Connection,
    node: dict,
    depth: int,
    include_sections: bool,
    include_tasks: bool,
    M: int = 4,
    source: str = "sections",
) -> dict:
    """Build the response dict for a single node, optionally with children/sections/tasks."""
    from db.pg_queries import get_node, get_children, get_sections, get_node_tasks
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
            # At M < 4 with a cached summary, skip full section load
            # unless the caller also asked for sections explicitly
            if not include_sections:
                if depth != 0:
                    children = await get_children(conn, node["id"])
                    next_depth = depth - 1 if depth > 0 else -1
                    result["children"] = []
                    for child in children:
                        result["children"].append(
                            await _build_node_response(
                                conn, child, next_depth, include_sections,
                                include_tasks, M, source,
                            )
                        )
                return result

    # Sections (full M=4 or fallback when no summary)
    if include_sections:
        all_sections = await get_sections(conn, node["id"])
        grouped: dict[str, list[dict]] = {}
        for s in all_sections:
            # Source filter
            if source == "memory" and s.get("origin") != "conversation_agent":
                continue
            if source == "sections" and s.get("origin") == "conversation_agent":
                continue
            # 'both' passes through all

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
        children = await get_children(conn, node["id"])
        next_depth = depth - 1 if depth > 0 else -1
        result["children"] = []
        for child in children:
            result["children"].append(
                await _build_node_response(
                    conn, child, next_depth, include_sections, include_tasks, M, source
                )
            )

    return result


async def _resolve_current_node_id(
    conn: asyncpg.Connection,
    conversation_id: str,
) -> str | None:
    """Return the context_node_id for a conversation, or None if unlinked."""
    import uuid as _uuid
    row = await conn.fetchrow(
        "SELECT context_node_id::text FROM conversations WHERE id = $1::uuid",
        _uuid.UUID(conversation_id),
    )
    if not row:
        return None
    return row["context_node_id"]


async def _check_scope(
    conn: asyncpg.Connection,
    node_id: str,
    current_node_id: str,
    N: int,
) -> bool:
    """Return True if node_id is within N tree-edges of current_node_id."""
    dist = await _tree_distance(conn, current_node_id, node_id, N)
    return dist is not None


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
) -> list:
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
        conversation_id: Current conversation UUID.
            Required for scope-envelope enforcement (N param). When absent,
            scope is not enforced and a warning is logged (legacy/debug use only).
            v2 will make this mandatory once Stream C callers always provide it.
        M: M-level detail for node data (1=title, 2=one-liner, 3=themes, 4=full).
            When M < 4, returns from node_data_summary cache if available;
            falls back to node_sections at M=4. No descent gating in v1.
        N: Scope envelope — max tree-edges from conversation's current_node.
            Requests outside N edges return {error: 'out_of_scope', target: <path>}.
            Only enforced when conversation_id is provided.
        source: 'sections' (default) | 'memory' | 'both'.
            'sections' — user-authored sections (origin='user').
            'memory'   — bot-authored sections (origin='conversation_agent').
            'both'     — all sections regardless of origin.

    Returns:
        List of node dicts (or error dicts for out-of-scope entries).
        If no paths and no node_ids, returns root nodes.
    """
    from db.pg_queries import get_node, get_node_by_path, get_children
    from db.pg_queries.node_memory import log_node_read

    # Resolve conversation scope
    current_node_id: str | None = None
    if conversation_id:
        current_node_id = await _resolve_current_node_id(conn, conversation_id)
        # Note: current_node_id may be None even when conversation_id is provided
        # (conversations without a linked context node skip scope enforcement)
    else:
        logger.warning(
            "read_context called without conversation_id (legacy/unscoped path) "
            "— scope envelope not enforced"
        )

    async def _fetch_and_check(node: dict) -> dict:
        """Apply scope check, log read, build response."""
        node_id = str(node["id"]) if not isinstance(node["id"], str) else node["id"]

        # Scope envelope check
        if current_node_id and N > 0:
            in_scope = await _check_scope(conn, node_id, current_node_id, N)
            if not in_scope:
                return {
                    "error": "out_of_scope",
                    "target": node_id,
                    "message": (
                        f"Node {node_id} is more than {N} tree-edges from "
                        f"conversation context node {current_node_id}. "
                        "Request permission via the conversation to access it."
                    ),
                }

        # Log read credit
        if conversation_id:
            try:
                await log_node_read(
                    conn, node_id, M,
                    conversation_id=conversation_id,
                    title=node.get("name"),
                )
            except Exception:
                pass  # don't fail the read if log fails

        return await _build_node_response(
            conn, node, depth, include_sections, include_tasks, M, source
        )

    # No args → return root nodes
    if not paths and not node_ids:
        roots = await get_children(conn, parent_id=None)
        result = []
        for root in roots:
            result.append(await _fetch_and_check(root))
        return result

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
