"""upsert_context tool — batch tree upsert with write modes, named sections, and reparenting."""

from __future__ import annotations

from pathlib import Path

from tether_mcp.common import get_db_path


def _resolve_parent(db_path: Path, parent_spec: str) -> str | None:
    """Resolve a parent spec (path or node_id) to a node_id, or None for root.

    Empty string means move to root (None).
    """
    from db.queries import get_node, get_node_by_path

    if parent_spec == "":
        return None

    # Try as direct node ID first (UUID-like)
    node = get_node(db_path, parent_spec)
    if node is not None:
        return node["id"]

    # Try as path
    node = get_node_by_path(db_path, parent_spec)
    if node is not None:
        return node["id"]

    raise ValueError(f"Parent not found: {parent_spec!r}")


def _process_node(
    db_path: Path,
    spec: dict,
    parent_id: str | None,
    results: list[dict],
) -> None:
    """Recursively process a node spec: create/update node, sections, and children."""
    from db.queries import (
        find_child_by_name,
        create_node,
        patch_node_fields,
        get_node,
        get_node_by_path,
        get_node_path,
        get_section,
        upsert_section,
        move_node,
    )
    from tether_mcp.write_modes import resolve_field, apply_text_mode, apply_resolved_field

    node_id_spec = spec.get("node_id") or ""
    name_raw = spec.get("name") or ""
    node_type = spec.get("node_type") or "context"
    description_raw = spec.get("description")
    target_date = spec.get("target_date") or None
    status = spec.get("status") or None
    color = spec.get("color") or None
    sections = spec.get("sections") or {}
    children = spec.get("children") or []
    parent_spec = spec.get("parent")

    # ── Resolve or walk to the target node ─────────────────────────────────

    node = None
    action = "updated"

    if node_id_spec:
        # Direct lookup by node_id
        node = get_node(db_path, node_id_spec)
        if node is None:
            raise ValueError(f"node_id not found: {node_id_spec!r}")
        # Rename if name provided and different
        if name_raw and name_raw != node["name"]:
            patch_node_fields(db_path, node["id"], {"name": name_raw})
            node = get_node(db_path, node["id"])
    else:
        # Walk slash-separated path, creating intermediates
        segments = [s for s in name_raw.split("/") if s]
        if not segments:
            raise ValueError("Node spec must have 'name' or 'node_id'")

        current_parent_id = parent_id
        for i, segment in enumerate(segments):
            is_last = (i == len(segments) - 1)
            existing = find_child_by_name(db_path, current_parent_id, segment)
            if existing is None:
                # Create intermediate or final node
                seg_type = node_type if is_last else "context"
                seg_status = (status or "pending") if is_last else "pending"
                seg_target_date = target_date if is_last else None
                seg_color = color if is_last else None
                new_node = create_node(
                    db_path,
                    parent_id=current_parent_id,
                    name=segment,
                    node_type=seg_type,
                    target_date=seg_target_date,
                    status=seg_status,
                    color=seg_color,
                )
                if is_last:
                    node = new_node
                    action = "created"
                current_parent_id = new_node["id"]
            else:
                if is_last:
                    node = get_node(db_path, existing["id"])
                    # action remains "updated"
                current_parent_id = existing["id"]

    node_id = node["id"]

    # ── Reparent if `parent` field provided ────────────────────────────────

    if parent_spec is not None:
        new_parent_id = _resolve_parent(db_path, parent_spec)
        move_node(db_path, node_id, new_parent_id)
        node = get_node(db_path, node_id)
        action = "moved"

    # ── Patch scalar fields (skip on fresh creates if already set) ─────────

    patch_fields: dict = {}

    # Patch node_type if different (not allowed by patch_node_fields, skip)
    # Update target_date, status, color for existing nodes
    # Update target_date, status, color for existing/moved nodes only
    # (for created nodes, fields were already set during create_node)
    if action != "created":
        if target_date is not None:
            patch_fields["target_date"] = target_date
        if status is not None:
            patch_fields["status"] = status
        if color is not None:
            patch_fields["color"] = color

    # ── Description with write modes ───────────────────────────────────────

    new_desc, _ = apply_resolved_field(description_raw, node.get("description") or "")
    if new_desc is not None:
        patch_fields["description"] = new_desc

    if patch_fields:
        patch_node_fields(db_path, node_id, patch_fields)
        node = get_node(db_path, node_id)

    # ── Sections with named files ───────────────────────────────────────────

    for section_type, files_dict in sections.items():
        if not isinstance(files_dict, dict):
            # Treat as a bare value for "main" file (backward compat)
            files_dict = {"main": files_dict}
        for filename, body_raw in files_dict.items():
            resolved = resolve_field(body_raw)
            if resolved is None:
                continue
            mode, value = resolved
            if mode == "replace":
                upsert_section(db_path, node_id, section_type, value, name=filename)
            elif mode in ("append", "patch"):
                existing_sec = get_section(db_path, node_id, section_type, filename)
                existing_body = existing_sec["body"] if existing_sec else ""
                result = apply_text_mode(existing_body, mode, value)
                if isinstance(result, tuple):
                    upsert_section(db_path, node_id, section_type, result[0], name=filename)
                else:
                    upsert_section(db_path, node_id, section_type, result, name=filename)

    # ── Build result entry ─────────────────────────────────────────────────

    node_path = get_node_path(db_path, node_id) or ""
    results.append({
        "id": node_id,
        "name": node["name"],
        "path": node_path,
        "node_type": node.get("node_type", "context"),
        "action": action,
    })

    # ── Recurse into children ───────────────────────────────────────────────

    for child_spec in children:
        _process_node(db_path, child_spec, node_id, results)


def execute_upsert_context(nodes: list[dict]) -> list[dict]:
    """Batch create or update context nodes with write modes, named sections, and reparenting.

    Each spec may contain:
        name           slash-separated path (e.g. "Projects/Tether/Phase 9")
        node_id        direct lookup; if name also given, treat as rename
        node_type      "context" (default) or "milestone"
        description    bare string or {mode, value} object
        target_date    ISO date string
        status         e.g. "pending", "done"
        color          hex color string
        parent         path or node_id to reparent to; "" = move to root
        sections       {section_type: {filename: body_or_object}}
        children       list of child node specs (recursive)

    Returns flat list of {id, name, path, node_type, action} dicts.
    """
    results: list[dict] = []
    db_path = get_db_path()

    for spec in nodes:
        _process_node(db_path, spec, parent_id=None, results=results)

    return results
