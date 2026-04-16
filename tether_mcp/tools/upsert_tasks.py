"""upsert_tasks tool — batch create/update tasks with write modes and linking."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def _get_db() -> Path:
    from tether_mcp.server import _db as get_db_path
    return get_db_path()


def execute_upsert_tasks(tasks: list[dict]) -> list[dict]:
    """Batch create or update tasks with write modes, scheduling, and linking.

    Each spec may contain:
        task_uuid, text, status, description, date, anchor_id, backlog,
        context_subject, node_ids, node_ids_remove, milestone_ids,
        blocked_by, blocked_by_remove, subtasks, subtasks_remove

    Returns list of {id, text, status, description, context_subject,
                     plan_date, anchor_id} dicts.
    """
    from db.queries import (
        get_task_by_uuid,
        patch_task_fields,
        upsert_plan,
        upsert_tasks as upsert_tasks_db,
        move_task_atomic,
        create_unscheduled_task,
        link_task_to_node,
        unlink_task_from_node,
        link_milestone_task,
        add_dependency,
        remove_dependency,
        get_dependencies_for,
        get_node_by_path,
        create_subtask,
        update_subtask,
        delete_subtask,
        get_subtasks,
    )
    from tether_mcp.batch import validate_no_duplicates
    from tether_mcp.write_modes import resolve_field, apply_text_mode

    validate_no_duplicates(tasks, key="task_uuid")

    db_path = _get_db()
    results: list[dict] = []

    for spec in tasks:
        task_uuid = spec.get("task_uuid") or ""
        text_raw = spec.get("text")
        description_raw = spec.get("description")
        status = spec.get("status") or ""
        date = spec.get("date") or ""
        anchor_id = spec.get("anchor_id") or ""
        backlog = spec.get("backlog", False)
        context_subject = spec.get("context_subject") or ""
        node_ids = spec.get("node_ids") or []
        node_ids_remove = spec.get("node_ids_remove") or []
        milestone_ids = spec.get("milestone_ids") or []
        blocked_by = spec.get("blocked_by") or []
        blocked_by_remove = spec.get("blocked_by_remove") or []
        subtasks = spec.get("subtasks") or []
        subtasks_remove = spec.get("subtasks_remove") or []

        if task_uuid:
            # --- UPDATE path ---
            patch_fields: dict = {}

            # Resolve text field
            text_resolved = resolve_field(text_raw)
            if text_resolved is not None:
                mode, value = text_resolved
                if mode == "replace":
                    patch_fields["text"] = value
                elif mode in ("append", "patch"):
                    existing_task = get_task_by_uuid(db_path, task_uuid)
                    existing_text = existing_task.get("text") if existing_task else None
                    result = apply_text_mode(existing_text, mode, value)
                    if isinstance(result, tuple):
                        patch_fields["text"] = result[0]
                    else:
                        patch_fields["text"] = result

            # Resolve description field
            desc_resolved = resolve_field(description_raw)
            if desc_resolved is not None:
                mode, value = desc_resolved
                if mode == "replace":
                    patch_fields["description"] = value
                elif mode in ("append", "patch"):
                    existing_task = get_task_by_uuid(db_path, task_uuid)
                    existing_desc = existing_task.get("description") if existing_task else None
                    result = apply_text_mode(existing_desc, mode, value)
                    if isinstance(result, tuple):
                        patch_fields["description"] = result[0]
                    else:
                        patch_fields["description"] = result

            # Scalar fields
            if status:
                patch_fields["status"] = status

            if patch_fields:
                patch_task_fields(db_path, task_uuid, patch_fields)

            # Scheduling
            if backlog:
                move_task_atomic(db_path, task_uuid, None, None)
            elif date and anchor_id:
                upsert_plan(db_path, date)
                move_task_atomic(db_path, task_uuid, date, anchor_id)

            final_task_id = task_uuid

        else:
            # --- CREATE path ---
            raw_text = text_raw if isinstance(text_raw, str) else (
                text_raw.get("value") if isinstance(text_raw, dict) else None
            )
            if not raw_text:
                raise ValueError("New tasks must have 'text'")

            raw_desc = description_raw if isinstance(description_raw, str) else (
                description_raw.get("value") if isinstance(description_raw, dict) else None
            )
            raw_status = status or "pending"
            raw_context = context_subject or None

            new_task = create_unscheduled_task(
                db_path, raw_text,
                description=raw_desc,
                status=raw_status,
                context_subject=raw_context,
            )
            final_task_id = new_task["id"]

            if date and anchor_id:
                upsert_plan(db_path, date)
                move_task_atomic(db_path, final_task_id, date, anchor_id)
            # context_subject already set on create; skip re-patching below if already done
            context_subject = ""  # don't re-apply below since already set

        # --- Post create/update operations ---

        # context_subject: patch + link via path
        if context_subject:
            patch_task_fields(db_path, final_task_id, {"context_subject": context_subject})
            node = get_node_by_path(db_path, context_subject)
            if node:
                link_task_to_node(db_path, node["id"], final_task_id)

        # node_ids: explicit link
        for nid in node_ids:
            link_task_to_node(db_path, nid, final_task_id)

        # node_ids_remove: explicit unlink
        for nid in node_ids_remove:
            unlink_task_from_node(db_path, nid, final_task_id)

        # milestone_ids: link
        for mid in milestone_ids:
            link_milestone_task(db_path, mid, final_task_id)

        # blocked_by: add dependencies
        for blocker_id in blocked_by:
            add_dependency(db_path, "task", blocker_id, "task", final_task_id)

        # blocked_by_remove: look up dep by entity_id then remove
        if blocked_by_remove:
            deps = get_dependencies_for(db_path, "task", final_task_id)
            for blocker_id in blocked_by_remove:
                for dep in deps.get("blocked_by", []):
                    if dep["entity_id"] == blocker_id:
                        remove_dependency(db_path, dep["id"])
                        break

        # subtasks: create new (no "id") or update existing (has "id")
        for sub in subtasks:
            if "id" in sub:
                update_subtask(db_path, sub["id"], **{
                    k: v for k, v in sub.items() if k != "id"
                })
            else:
                # Determine position: after existing subtasks
                existing_subs = get_subtasks(db_path, final_task_id)
                pos = len(existing_subs)
                create_subtask(db_path, final_task_id, sub["text"], position=pos)

        # subtasks_remove: delete by id
        for sub_id in subtasks_remove:
            delete_subtask(db_path, sub_id)

        # Fetch final state
        final = get_task_by_uuid(db_path, final_task_id)
        if final:
            results.append({
                "id": final.get("id"),
                "text": final.get("text"),
                "status": final.get("status"),
                "description": final.get("description"),
                "context_subject": final.get("context_subject"),
                "plan_date": final.get("plan_date"),
                "anchor_id": final.get("anchor_id"),
            })

    return results
