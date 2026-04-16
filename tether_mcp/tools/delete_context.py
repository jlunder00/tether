"""delete_context tool — batch delete context nodes or clear specific node content."""

from __future__ import annotations

from tether_mcp.common import get_db_path


def execute_delete_context(operations: list[dict]) -> list[dict]:
    """Batch delete context nodes or clear specific node content.

    Each operation dict:
        node_id           direct node ID (one of node_id or path required)
        path              slash-separated path to resolve (e.g. "Projects/Tether")
        delete            bool — delete entire node (CASCADE deletes children, sections, task links).
                          If True, ignores all other flags.
        archive           bool — set archived=1 (reversible). Takes precedence over field clearing.
        clear_sections    list[str] — section types to clear entirely (all files in that type)
        delete_files      list[dict] — specific files to delete: [{section_type, name}]
        clear_description bool — set description to None
        clear_task_links  bool — delete all node_tasks rows for this node

    Returns list of {node_id, path, action, cleared?}.
    """
    from db.queries import (
        get_node,
        get_node_by_path,
        get_node_path,
        patch_node_fields,
        list_section_files,
        delete_section,
    )
    from db.schema import get_db

    db_path = get_db_path()
    results: list[dict] = []

    for op in operations:
        node_id = op.get("node_id") or ""
        path_spec = op.get("path") or ""

        # Resolve node
        node = None
        if node_id:
            node = get_node(db_path, node_id)
            if node is None:
                raise ValueError(f"Node not found: {node_id!r}")
        elif path_spec:
            node = get_node_by_path(db_path, path_spec)
            if node is None:
                raise ValueError(f"Node not found at path: {path_spec!r}")
        else:
            raise ValueError("Each operation must have 'node_id' or 'path'")

        node_id = node["id"]
        node_path = get_node_path(db_path, node_id) or ""

        delete = op.get("delete", False)

        if delete:
            with get_db(db_path) as conn:
                conn.execute("DELETE FROM context_nodes WHERE id = ?", (node_id,))
            results.append({"node_id": node_id, "path": node_path, "action": "deleted"})
            continue

        archive = op.get("archive", False)

        if archive:
            patch_node_fields(db_path, node_id, {"archived": 1})
            results.append({"node_id": node_id, "path": node_path, "action": "archived"})
            continue

        # Selective clearing
        cleared: list[str] = []

        if op.get("clear_description"):
            patch_node_fields(db_path, node_id, {"description": None})
            cleared.append("description")

        clear_sections = op.get("clear_sections") or []
        for section_type in clear_sections:
            files = list_section_files(db_path, node_id, section_type)
            for f in files:
                delete_section(db_path, node_id, section_type, name=f["name"])
            cleared.append(f"section:{section_type}")

        delete_files = op.get("delete_files") or []
        for file_spec in delete_files:
            st = file_spec.get("section_type") or ""
            name = file_spec.get("name") or "main"
            if not st:
                raise ValueError("delete_files entries must have 'section_type'")
            delete_section(db_path, node_id, st, name=name)
            cleared.append(f"file:{st}/{name}")

        if op.get("clear_task_links"):
            with get_db(db_path) as conn:
                conn.execute("DELETE FROM node_tasks WHERE node_id = ?", (node_id,))
            cleared.append("task_links")

        results.append({
            "node_id": node_id,
            "path": node_path,
            "action": "cleared",
            "cleared": cleared,
        })

    return results
