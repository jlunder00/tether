"""read_context tool — batched reads with depth traversal, sections (cat -n), and tasks."""

from __future__ import annotations

import asyncpg


async def _build_node_response(
    conn: asyncpg.Connection,
    node: dict,
    depth: int,
    include_sections: bool,
    include_tasks: bool,
) -> dict:
    """Build the response dict for a single node, optionally with children/sections/tasks."""
    from db.pg_queries import get_node, get_children, get_sections, get_node_tasks
    from tether_mcp.write_modes import format_cat_n, line_count

    # Ensure we have full node dict (with section_types and children_count)
    if "section_types" not in node or "children_count" not in node:
        full = await get_node(conn, node["id"])
        if full is None:
            return node
        node = full

    result = dict(node)

    # Sections
    if include_sections:
        all_sections = await get_sections(conn, node["id"])
        grouped: dict[str, list[dict]] = {}
        for s in all_sections:
            st = s["section_type"]
            if st not in grouped:
                grouped[st] = []
            body = s["body"] or ""
            grouped[st].append({
                "name": s["name"],
                "body": format_cat_n(body),
                "line_count": line_count(body),
            })
        result["sections"] = grouped

    # Tasks
    if include_tasks:
        result["tasks"] = await get_node_tasks(conn, node["id"])

    # Children (recursive)
    if depth != 0:
        children = await get_children(conn, node["id"])
        next_depth = depth - 1 if depth > 0 else -1  # -1 means unlimited
        result["children"] = []
        for child in children:
            result["children"].append(
                await _build_node_response(conn, child, next_depth, include_sections, include_tasks)
            )

    return result


async def execute_read_context(
    conn: asyncpg.Connection,
    paths=None,
    node_ids=None,
    depth: int = 0,
    include_sections: bool = False,
    include_tasks: bool = False,
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
            Each section entry has {name, body (cat -n format), line_count}.
        include_tasks: If True, add "tasks" list from get_node_tasks.

    Returns:
        List of node dicts (or None for not-found entries), in same order as inputs.
        If no paths and no node_ids, returns root nodes.
    """
    from db.pg_queries import get_node, get_node_by_path, get_children

    # No args → return root nodes
    if not paths and not node_ids:
        roots = await get_children(conn, parent_id=None)
        result = []
        for root in roots:
            result.append(
                await _build_node_response(conn, root, depth, include_sections, include_tasks)
            )
        return result

    results = []

    # Resolve paths
    for path in (paths or []):
        node = await get_node_by_path(conn, path)
        if node is None:
            results.append(None)
        else:
            results.append(
                await _build_node_response(conn, node, depth, include_sections, include_tasks)
            )

    # Resolve node_ids
    for nid in (node_ids or []):
        node = await get_node(conn, nid)
        if node is None:
            results.append(None)
        else:
            results.append(
                await _build_node_response(conn, node, depth, include_sections, include_tasks)
            )

    return results
