"""read_tasks tool — filtered task reads with optional deps/subtasks expansion."""

from __future__ import annotations

from typing import Optional

from tether_mcp.common import get_db_path


def execute_read_tasks(
    task_ids: Optional[list[str]] = None,
    status: str = "",
    context: str = "",
    milestone_id: str = "",
    date: str = "",
    anchor_id: str = "",
    unscheduled: bool = False,
    include_deps: bool = False,
    include_subtasks: bool = False,
) -> list[dict]:
    """Fetch tasks with optional filters and expansion.

    Args:
        task_ids: If provided, fetch these specific tasks by UUID.
        status: Filter by task.status (exact match).
        context: Filter by task.context_subject (exact match).
        milestone_id: Filter to tasks linked via milestone_tasks table.
        date: Filter by task.plan_date (exact match).
        anchor_id: Filter by task.anchor_id (exact match).
        unscheduled: If True, return only tasks with plan_date=None.
        include_deps: If True, add "deps" key with blocks/blocked_by.
        include_subtasks: If True, add "subtasks" key.

    Returns:
        List of task dicts. Keys always present: id, text, status, description,
        context_subject, plan_date, anchor_id. "deps" and "subtasks" present only
        when the corresponding include_* flag is True.
    """
    from db.queries import get_all_tasks, get_task_by_uuid, get_dependencies_for, get_subtasks
    from db.schema import get_db

    db_path = get_db_path()

    # Fetch tasks
    if task_ids:
        raw_tasks = []
        for tid in task_ids:
            t = get_task_by_uuid(db_path, tid)
            raw_tasks.append(t)  # None preserved for missing IDs (matching read_context behaviour)
    else:
        raw_tasks = get_all_tasks(db_path)

        # Apply filters (AND'd together)
        if status:
            raw_tasks = [t for t in raw_tasks if t.get("status") == status]
        if context:
            raw_tasks = [t for t in raw_tasks if t.get("context_subject") == context]
        if date:
            raw_tasks = [t for t in raw_tasks if t.get("plan_date") == date]
        if anchor_id:
            raw_tasks = [t for t in raw_tasks if t.get("anchor_id") == anchor_id]
        if unscheduled:
            raw_tasks = [t for t in raw_tasks if t.get("plan_date") is None]
        if milestone_id:
            with get_db(db_path) as conn:
                rows = conn.execute(
                    "SELECT task_id FROM milestone_tasks WHERE milestone_id = ?",
                    (milestone_id,),
                ).fetchall()
            linked_ids = {r["task_id"] for r in rows}
            raw_tasks = [t for t in raw_tasks if t.get("id") in linked_ids]

    # Build response dicts
    result = []
    for t in raw_tasks:
        if t is None:
            result.append(None)
            continue

        task_dict = {
            "id": t.get("id"),
            "text": t.get("text"),
            "status": t.get("status"),
            "description": t.get("description"),
            "context_subject": t.get("context_subject"),
            "plan_date": t.get("plan_date"),
            "anchor_id": t.get("anchor_id"),
        }

        if include_deps:
            task_dict["deps"] = get_dependencies_for(db_path, "task", t["id"])

        if include_subtasks:
            task_dict["subtasks"] = get_subtasks(db_path, t["id"])

        result.append(task_dict)

    return result
