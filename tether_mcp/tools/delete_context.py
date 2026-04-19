"""delete_context tool — batch delete context nodes or clear specific node content."""

from __future__ import annotations

import asyncpg


async def execute_delete_context(conn: asyncpg.Connection, operations: list[dict]) -> list[dict]:
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
    from db.pg_queries import (
        get_node,
        get_node_by_path,
        get_node_path,
        patch_node_fields,
        list_section_files,
        delete_section,
    )

    results: list[dict] = []

    for op in operations:
        node_id = op.get("node_id") or ""
        path_spec = op.get("path") or ""

        # Resolve node
        node = None
        if node_id:
            node = await get_node(conn, node_id)
            if node is None:
                raise ValueError(f"Node not found: {node_id!r}")
        elif path_spec:
            node = await get_node_by_path(conn, path_spec)
            if node is None:
                raise ValueError(f"Node not found at path: {path_spec!r}")
        else:
            raise ValueError("Each operation must have 'node_id' or 'path'")

        node_id = node["id"]
        node_path = await get_node_path(conn, node_id) or ""

        delete = op.get("delete", False)

        if delete:
            await conn.execute("DELETE FROM context_nodes WHERE id = $1", node_id)
            results.append({"node_id": node_id, "path": node_path, "action": "deleted"})
            continue

        archive = op.get("archive", False)

        if archive:
            await patch_node_fields(conn, node_id, {"archived": 1})
            results.append({"node_id": node_id, "path": node_path, "action": "archived"})
            continue

        # Selective clearing
        cleared: list[str] = []

        if op.get("clear_description"):
            await patch_node_fields(conn, node_id, {"description": None})
            cleared.append("description")

        clear_sections = op.get("clear_sections") or []
        for section_type in clear_sections:
            files = await list_section_files(conn, node_id, section_type)
            for f in files:
                await delete_section(conn, node_id, section_type, name=f["name"])
            cleared.append(f"section:{section_type}")

        delete_files = op.get("delete_files") or []
        for file_spec in delete_files:
            st = file_spec.get("section_type") or ""
            name = file_spec.get("name") or "main"
            if not st:
                raise ValueError("delete_files entries must have 'section_type'")
            await delete_section(conn, node_id, st, name=name)
            cleared.append(f"file:{st}/{name}")

        if op.get("clear_task_links"):
            await conn.execute("DELETE FROM node_tasks WHERE node_id = $1", node_id)
            cleared.append("task_links")

        results.append({
            "node_id": node_id,
            "path": node_path,
            "action": "cleared",
            "cleared": cleared,
        })

    return results
