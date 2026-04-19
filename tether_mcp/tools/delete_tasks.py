"""delete_tasks tool — batch delete tasks or clear specific task content."""

from __future__ import annotations

import asyncpg


async def execute_delete_tasks(conn: asyncpg.Connection, operations: list[dict]) -> list[dict]:
    """Batch delete tasks or clear specific task content.

    Each operation dict:
        task_uuid         (required) UUID of the task
        delete            bool — delete entire task (cascades). If True, ignores all other flags.
        clear_description bool — set description to None
        clear_subtasks    bool — delete all subtasks
        clear_deps        bool — delete all dependencies (both blocks and blocked_by)
        clear_node_links  bool — delete all node_tasks and milestone_tasks links
        clear_context     bool — set context_subject to None

    Returns list of {task_uuid, action, cleared?} where action is "deleted" or "cleared"
    (with `cleared` list of what was cleared).
    """
    from db.pg_queries import (
        get_task_by_uuid,
        delete_task_by_uuid,
        patch_task_fields,
        get_subtasks,
        delete_subtask,
    )

    results: list[dict] = []

    for op in operations:
        task_uuid = op.get("task_uuid") or ""
        if not task_uuid:
            raise ValueError("Each operation must have 'task_uuid'")

        task = await get_task_by_uuid(conn, task_uuid)
        if task is None:
            raise ValueError(f"Task not found: {task_uuid!r}")

        delete = op.get("delete", False)

        if delete:
            await delete_task_by_uuid(conn, task_uuid)
            results.append({"task_uuid": task_uuid, "action": "deleted"})
            continue

        # Selective clearing
        cleared: list[str] = []

        if op.get("clear_description"):
            await patch_task_fields(conn, task_uuid, {"description": None})
            cleared.append("description")

        if op.get("clear_subtasks"):
            subtasks = await get_subtasks(conn, task_uuid)
            for sub in subtasks:
                await delete_subtask(conn, sub["id"])
            cleared.append("subtasks")

        if op.get("clear_deps"):
            await conn.execute(
                "DELETE FROM dependencies WHERE "
                "(blocker_type='task' AND blocker_id=$1) OR "
                "(blocked_type='task' AND blocked_id=$2)",
                task_uuid, task_uuid,
            )
            cleared.append("deps")

        if op.get("clear_node_links"):
            await conn.execute("DELETE FROM node_tasks WHERE task_id = $1", task_uuid)
            await conn.execute("DELETE FROM milestone_tasks WHERE task_id = $1", task_uuid)
            cleared.append("node_links")

        if op.get("clear_context"):
            await patch_task_fields(conn, task_uuid, {"context_subject": None})
            cleared.append("context")

        result: dict = {"task_uuid": task_uuid, "action": "cleared", "cleared": cleared}
        results.append(result)

    return results
