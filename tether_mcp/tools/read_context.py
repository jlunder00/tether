"""read_context tool — batched reads with depth traversal, sections (cat -n), and tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def _get_db() -> Path:
    from tether_mcp.server import _db as get_db_path
    return get_db_path()


def _build_node_response(
    db_path: Path,
    node: dict,
    depth: int,
    include_sections: bool,
    include_tasks: bool,
) -> dict:
    """Build the response dict for a single node, optionally with children/sections/tasks."""
    from db.queries import get_node, get_children, get_sections, get_node_tasks
    from tether_mcp.write_modes import format_cat_n, line_count

    # Ensure we have full node dict (with section_types and children_count)
    if "section_types" not in node or "children_count" not in node:
        full = get_node(db_path, node["id"])
        if full is None:
            return node
        node = full

    result = dict(node)

    # Sections
    if include_sections:
        all_sections = get_sections(db_path, node["id"])
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
        result["tasks"] = get_node_tasks(db_path, node["id"])

    # Children (recursive)
    if depth != 0:
        children = get_children(db_path, node["id"])
        next_depth = depth - 1 if depth > 0 else -1  # -1 means unlimited
        result["children"] = [
            _build_node_response(db_path, child, next_depth, include_sections, include_tasks)
            for child in children
        ]

    return result


def execute_read_context(
    paths: Optional[list[str]] = None,
    node_ids: Optional[list[str]] = None,
    depth: int = 0,
    include_sections: bool = False,
    include_tasks: bool = False,
) -> list[Optional[dict]]:
    """Fetch context nodes with optional depth traversal, section content, and linked tasks.

    Args:
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
    from db.queries import get_node, get_node_by_path, get_children

    db_path = _get_db()

    # No args → return root nodes
    if not paths and not node_ids:
        roots = get_children(db_path, parent_id=None)
        return [
            _build_node_response(db_path, root, depth, include_sections, include_tasks)
            for root in roots
        ]

    results: list[Optional[dict]] = []

    # Resolve paths
    for path in (paths or []):
        node = get_node_by_path(db_path, path)
        if node is None:
            results.append(None)
        else:
            # get_node_by_path already calls get_node internally, so full dict is returned
            results.append(
                _build_node_response(db_path, node, depth, include_sections, include_tasks)
            )

    # Resolve node_ids
    for nid in (node_ids or []):
        node = get_node(db_path, nid)
        if node is None:
            results.append(None)
        else:
            results.append(
                _build_node_response(db_path, node, depth, include_sections, include_tasks)
            )

    return results
