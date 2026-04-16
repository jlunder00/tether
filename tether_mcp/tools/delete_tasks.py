"""delete_tasks tool — batch delete tasks or clear specific task content."""

from __future__ import annotations

from tether_mcp.common import get_db_path
from db.schema import transaction


def execute_delete_tasks(operations: list[dict]) -> list[dict]:
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
    from db.queries import (
        get_task_by_uuid,
        delete_task_by_uuid,
        patch_task_fields,
        get_subtasks,
        delete_subtask,
    )
    from db.schema import get_db

    db_path = get_db_path()
    results: list[dict] = []

    with transaction(db_path):
        for op in operations:
            task_uuid = op.get("task_uuid") or ""
            if not task_uuid:
                raise ValueError("Each operation must have 'task_uuid'")

            task = get_task_by_uuid(db_path, task_uuid)
            if task is None:
                raise ValueError(f"Task not found: {task_uuid!r}")

            delete = op.get("delete", False)

            if delete:
                delete_task_by_uuid(db_path, task_uuid)
                results.append({"task_uuid": task_uuid, "action": "deleted"})
                continue

            # Selective clearing
            cleared: list[str] = []

            if op.get("clear_description"):
                patch_task_fields(db_path, task_uuid, {"description": None})
                cleared.append("description")

            if op.get("clear_subtasks"):
                subtasks = get_subtasks(db_path, task_uuid)
                for sub in subtasks:
                    delete_subtask(db_path, sub["id"])
                cleared.append("subtasks")

            if op.get("clear_deps"):
                with get_db(db_path) as conn:
                    conn.execute(
                        "DELETE FROM dependencies WHERE "
                        "(blocker_type='task' AND blocker_id=?) OR "
                        "(blocked_type='task' AND blocked_id=?)",
                        (task_uuid, task_uuid),
                    )
                cleared.append("deps")

            if op.get("clear_node_links"):
                with get_db(db_path) as conn:
                    conn.execute("DELETE FROM node_tasks WHERE task_id = ?", (task_uuid,))
                    conn.execute("DELETE FROM milestone_tasks WHERE task_id = ?", (task_uuid,))
                cleared.append("node_links")

            if op.get("clear_context"):
                patch_task_fields(db_path, task_uuid, {"context_subject": None})
                cleared.append("context")

            result: dict = {"task_uuid": task_uuid, "action": "cleared", "cleared": cleared}
            results.append(result)

    return results
