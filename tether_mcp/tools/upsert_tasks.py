"""upsert_tasks tool — batch create/update tasks with write modes and linking."""

from __future__ import annotations

import asyncpg


async def execute_upsert_tasks(conn: asyncpg.Connection, tasks: list[dict]) -> list[dict]:
    """Batch create or update tasks with write modes, scheduling, and linking.

    Each spec may contain:
        task_uuid, text, status, description, date, anchor_id, backlog,
        context_subject, node_ids, node_ids_remove, milestone_ids,
        blocked_by, blocked_by_remove, subtasks, subtasks_remove

    Returns list of {id, text, status, description, context_subject,
                     plan_date, anchor_id} dicts.
    """
    from db.pg_queries import (
        get_task_by_uuid,
        patch_task_fields,
        upsert_plan,
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
    from tether_mcp.write_modes import apply_resolved_field

    validate_no_duplicates(tasks, key="task_uuid")

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

            # Fetch existing task once for write-mode resolution
            existing_task = await get_task_by_uuid(conn, task_uuid)

            # Resolve text field
            new_text, _ = apply_resolved_field(
                text_raw,
                existing_task.get("text") if existing_task else None,
            )
            if new_text is not None:
                patch_fields["text"] = new_text

            # Resolve description field
            new_desc, _ = apply_resolved_field(
                description_raw,
                existing_task.get("description") if existing_task else None,
            )
            if new_desc is not None:
                patch_fields["description"] = new_desc

            # Scalar fields
            if status:
                patch_fields["status"] = status

            if patch_fields:
                await patch_task_fields(conn, task_uuid, patch_fields)

            # Scheduling
            if backlog:
                await move_task_atomic(conn, task_uuid, None, None)
            elif date and anchor_id:
                await upsert_plan(conn, date)
                await move_task_atomic(conn, task_uuid, date, anchor_id)

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

            new_task = await create_unscheduled_task(
                conn, raw_text,
                description=raw_desc,
                status=raw_status,
                context_subject=raw_context,
            )
            final_task_id = new_task["id"]

            if date and anchor_id:
                await upsert_plan(conn, date)
                await move_task_atomic(conn, final_task_id, date, anchor_id)
            # context_subject already set on create; skip re-patching below if already done
            context_subject = ""  # don't re-apply below since already set

        # --- Post create/update operations ---

        # context_subject: patch + link via path
        if context_subject:
            await patch_task_fields(conn, final_task_id, {"context_subject": context_subject})
            node = await get_node_by_path(conn, context_subject)
            if node:
                await link_task_to_node(conn, node["id"], final_task_id)

        # node_ids: explicit link
        for nid in node_ids:
            await link_task_to_node(conn, nid, final_task_id)

        # node_ids_remove: explicit unlink
        for nid in node_ids_remove:
            await unlink_task_from_node(conn, nid, final_task_id)

        # milestone_ids: link
        for mid in milestone_ids:
            await link_milestone_task(conn, mid, final_task_id)

        # blocked_by: add dependencies
        for blocker_id in blocked_by:
            await add_dependency(conn, "task", blocker_id, "task", final_task_id)

        # blocked_by_remove: look up dep by entity_id then remove
        if blocked_by_remove:
            deps = await get_dependencies_for(conn, "task", final_task_id)
            for blocker_id in blocked_by_remove:
                for dep in deps.get("blocked_by", []):
                    if dep["entity_id"] == blocker_id:
                        await remove_dependency(conn, dep["id"])
                        break

        # subtasks: create new (no "id") or update existing (has "id")
        for sub in subtasks:
            if "id" in sub:
                await update_subtask(conn, sub["id"], **{
                    k: v for k, v in sub.items() if k != "id"
                })
            else:
                # Determine position: after existing subtasks
                existing_subs = await get_subtasks(conn, final_task_id)
                pos = len(existing_subs)
                await create_subtask(conn, final_task_id, sub["text"], position=pos)

        # subtasks_remove: delete by id
        for sub_id in subtasks_remove:
            await delete_subtask(conn, sub_id)

        # Fetch final state
        final = await get_task_by_uuid(conn, final_task_id)
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
        else:
            results.append({"error": "task not found after mutation", "task_uuid": final_task_id})

    return results
