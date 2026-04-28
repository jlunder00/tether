"""upsert_tasks tool — batch create/update tasks with write modes and linking."""

from __future__ import annotations

import asyncpg

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
    promote_task_to_event,
    update_event_time,
)
from tether_mcp.batch import validate_no_duplicates
from tether_mcp.write_modes import apply_resolved_field


_ABSENT = object()


async def execute_upsert_tasks(conn: asyncpg.Connection, tasks: list[dict]) -> list[dict]:
    """Batch create or update tasks with write modes, scheduling, and linking.

    Each spec may contain:
        task_uuid, text, status, description, date, anchor_id, backlog,
        context_subject, node_ids, node_ids_remove, milestone_ids,
        blocked_by, blocked_by_remove, subtasks, subtasks_remove,
        start_time, end_time, rrule, color

    Returns list of {id, text, status, description, context_subject,
                     plan_date, anchor_id} dicts.
    """
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

        start_time = spec.get("start_time") or ""
        end_time = spec.get("end_time") or ""
        rrule = spec.get("rrule", _ABSENT)
        color = spec.get("color", _ABSENT)

        if bool(start_time) != bool(end_time):
            missing = "end_time" if start_time else "start_time"
            raise ValueError(
                f"upsert_tasks: {missing} is required when the other event time field is provided"
            )
        if start_time and end_time and start_time >= end_time:
            raise ValueError("upsert_tasks: start_time must be before end_time")

        if task_uuid:
            # --- UPDATE path ---
            patch_fields: dict = {}

            existing_task = await get_task_by_uuid(conn, task_uuid)

            new_text, _ = apply_resolved_field(
                text_raw,
                existing_task.get("text") if existing_task else None,
            )
            if new_text is not None:
                patch_fields["text"] = new_text

            new_desc, _ = apply_resolved_field(
                description_raw,
                existing_task.get("description") if existing_task else None,
            )
            if new_desc is not None:
                patch_fields["description"] = new_desc

            if status:
                patch_fields["status"] = status

            if rrule is not _ABSENT:
                patch_fields["rrule"] = rrule
            if color is not _ABSENT:
                patch_fields["color"] = color

            if patch_fields:
                await patch_task_fields(conn, task_uuid, patch_fields)

            if backlog:
                await move_task_atomic(conn, task_uuid, None, None)
            elif date and anchor_id:
                await upsert_plan(conn, date)
                await move_task_atomic(conn, task_uuid, date, anchor_id)

            if start_time and end_time:
                await update_event_time(conn, task_uuid, start_time, end_time)

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
            # context_subject already set on create; skip re-patching below
            context_subject = ""

            if start_time and end_time:
                await promote_task_to_event(conn, final_task_id, start_time, end_time)

            event_fields: dict = {}
            if rrule is not _ABSENT and rrule is not None:
                event_fields["rrule"] = rrule
            if color is not _ABSENT and color is not None:
                event_fields["color"] = color
            if event_fields:
                await patch_task_fields(conn, final_task_id, event_fields)

        # --- Post create/update operations ---

        if context_subject:
            await patch_task_fields(conn, final_task_id, {"context_subject": context_subject})
            node = await get_node_by_path(conn, context_subject)
            if node:
                await link_task_to_node(conn, node["id"], final_task_id)

        for nid in node_ids:
            await link_task_to_node(conn, nid, final_task_id)

        for nid in node_ids_remove:
            await unlink_task_from_node(conn, nid, final_task_id)

        for mid in milestone_ids:
            await link_milestone_task(conn, mid, final_task_id)

        for blocker_id in blocked_by:
            await add_dependency(conn, "task", blocker_id, "task", final_task_id)

        if blocked_by_remove:
            deps = await get_dependencies_for(conn, "task", final_task_id)
            for blocker_id in blocked_by_remove:
                for dep in deps.get("blocked_by", []):
                    if dep["entity_id"] == blocker_id:
                        await remove_dependency(conn, dep["id"])
                        break

        for sub in subtasks:
            if "id" in sub:
                await update_subtask(conn, sub["id"], **{
                    k: v for k, v in sub.items() if k != "id"
                })
            else:
                existing_subs = await get_subtasks(conn, final_task_id)
                pos = len(existing_subs)
                await create_subtask(conn, final_task_id, sub["text"], position=pos)

        for sub_id in subtasks_remove:
            await delete_subtask(conn, sub_id)

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
