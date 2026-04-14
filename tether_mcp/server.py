from __future__ import annotations
import json
import os
from datetime import date as date_type, datetime
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from db.queries import (
    get_anchors as _db_get_anchors,
    get_invocation_log,
    get_plan,
    upsert_plan,
    upsert_tasks,
    patch_task_fields,
    search_entities,
    add_dependency,
    remove_dependency,
    get_dependencies_for,
    get_subtasks,
    create_subtask,
    update_subtask,
    delete_subtask,
    link_milestone_task,
    create_unscheduled_task,
    get_task_by_uuid,
    move_task_atomic,
    delete_task_by_uuid,
)

mcp = FastMCP("tether", host="0.0.0.0", port=5001)


def _load_secrets() -> dict:
    p = Path.home() / ".tether-config" / "secrets.json"
    if p.exists():
        import json
        return json.loads(p.read_text())
    return {}

_secrets = _load_secrets()

def _db() -> Path:
    env = os.environ.get("TETHER_DB_PATH")
    if env:
        return Path(env)
    user_id = os.environ.get("TETHER_USER_ID") or _secrets.get("TETHER_USER_ID")
    if user_id:
        return Path.home() / ".tether-config" / "users" / f"{user_id}.db"
    return Path.home() / ".tether-config" / "tether.db"


def _current_anchor(anchors: list[dict], now: Optional[datetime] = None) -> dict:
    if now is None:
        now = datetime.now()
    today = now.date()

    def anchor_start(a: dict) -> datetime:
        h, m = map(int, a["time"].split(":"))
        return datetime(today.year, today.month, today.day, h, m)

    active = anchors[0]
    for anchor in anchors:
        if now >= anchor_start(anchor):
            active = anchor
        else:
            break
    return active


# --- Internal functions (testable directly) ---

def _get_today_plan(date: str | None = None) -> dict:
    d = date or str(date_type.today())
    return get_plan(_db(), d)


def _update_plan_tasks(anchor_id: str, tasks: list, date: str | None = None) -> list[dict]:
    d = date or str(date_type.today())
    upsert_plan(_db(), d)
    return upsert_tasks(_db(), d, anchor_id, tasks, notes="")


def _get_anchors() -> list[dict]:
    return _db_get_anchors(_db())


def _get_current_anchor() -> dict:
    return _current_anchor(_db_get_anchors(_db()))


# --- MCP tool wrappers ---

@mcp.tool()
def get_today_plan(date: str = "") -> dict:
    """Get the anchor plan for a given date. Pass YYYY-MM-DD or leave empty for today."""
    return _get_today_plan(date or None)


@mcp.tool()
def upsert_task(
    text: str = "",
    task_uuid: str = "",
    status: str = "",
    description: str = "",
    date: str = "",
    anchor_id: str = "",
    backlog: bool = False,
    context_subject: str = "",
    milestone_ids: list[str] = [],
    blocked_by: list[str] = [],
) -> dict:
    """Create or update a task in one call. All fields optional except:
    - To CREATE: must provide 'text'. Lands in backlog unless date+anchor_id given.
    - To UPDATE: must provide 'task_uuid'. Only provided fields are changed.

    Fields:
    - text: task title (required for create, optional for update)
    - task_uuid: existing task UUID (omit to create new)
    - status: pending/in_progress/done/skipped/blocked
    - description: detailed description text
    - date + anchor_id: schedule to a specific day+anchor
    - backlog: True to unschedule (move to backlog)
    - context_subject: context entry subject to link (replaces existing)
    - milestone_ids: list of milestone IDs to link (additive)
    - blocked_by: list of task/milestone UUIDs that block this task (additive)

    Returns the task dict with id, text, status, etc."""
    db = _db()

    if task_uuid:
        # UPDATE existing task
        patch_fields = {}
        if text:
            patch_fields["text"] = text
        if status:
            patch_fields["status"] = status
        if description:
            patch_fields["description"] = description
        if patch_fields:
            patch_task_fields(db, task_uuid, patch_fields)

        # Move if requested
        if backlog:
            move_task_atomic(db, task_uuid, None, None)
        elif date and anchor_id:
            move_task_atomic(db, task_uuid, date, anchor_id)

        result_task = get_task_by_uuid(db, task_uuid)
    else:
        # CREATE new task
        if not text:
            return {"error": "text is required to create a new task"}

        if date and anchor_id:
            # Scheduled task
            upsert_plan(db, date)
            tasks_result = upsert_tasks(db, date, anchor_id, [
                {"text": text, "status": status or "pending",
                 "context_subject": context_subject or None}
            ])
            new_task = next((t for t in tasks_result if t["text"] == text), tasks_result[-1])
            task_uuid = new_task["id"]
        else:
            # Backlog task
            new_task = create_unscheduled_task(db, text,
                                               description=description or None,
                                               status=status or "pending",
                                               context_subject=context_subject or None)
            task_uuid = new_task["id"]

        if description and date and anchor_id:
            # Scheduled task needs description set separately
            patch_task_fields(db, task_uuid, {"description": description})

        result_task = get_task_by_uuid(db, task_uuid)

    # Set context (replaces existing)
    if context_subject and task_uuid:
        patch_task_fields(db, task_uuid, {"context_subject": context_subject})

    # Link milestones (additive — INSERT OR IGNORE handles duplicates)
    for mid in milestone_ids:
        link_milestone_task(db, mid, task_uuid)

    # Add blockers (additive — INSERT OR IGNORE handles duplicates)
    for blocker_id in blocked_by:
        add_dependency(db, "task", blocker_id, "task", task_uuid)

    return result_task or {"id": task_uuid, "text": text, "status": status or "pending"}


@mcp.tool()
def update_plan_tasks(anchor_id: str, tasks: list, date: str = "") -> dict:
    """Add or update tasks for an anchor. Never deletes — use remove_task to delete.
    Each item can be:
    - A plain string: creates a new task with that text
    - A dict with 'id': updates that existing task (pass text/status to change them)
    - A dict with 'text' only: creates a new task
    Returns the full task list for this anchor after changes."""
    return _update_plan_tasks(anchor_id, tasks, date or None)


@mcp.tool()
def remove_task(task_uuid: str) -> dict:
    """Permanently delete a task by UUID. Cascades to subtasks, links, dependencies, milestones."""
    delete_task_by_uuid(_db(), task_uuid)
    return {"ok": True, "deleted": task_uuid}


@mcp.tool()
def move_to_backlog(task_uuid: str) -> dict:
    """Move a task to the backlog (unschedule it). Preserves all milestone/context/dep links."""
    move_task_atomic(_db(), task_uuid, None, None)
    return {"ok": True, "moved": task_uuid}


@mcp.tool()
def schedule_task(task_uuid: str, date: str, anchor_id: str) -> dict:
    """Schedule a backlog task onto a specific date and anchor."""
    move_task_atomic(_db(), task_uuid, date, anchor_id)
    return {"ok": True, "scheduled": task_uuid, "date": date, "anchor_id": anchor_id}


@mcp.tool()
def get_anchors() -> list[dict]:
    """Get all anchor definitions (id, name, time, duration, color)."""
    return _get_anchors()


@mcp.tool()
def get_current_anchor() -> dict:
    """Get the currently active anchor based on the current time."""
    return _get_current_anchor()


@mcp.tool()
def get_bot_log(n: int = 5) -> list[dict]:
    """Get the last n bot invocation sessions from the pipeline log.
    Each entry has: session_id, stage, prompt, response, error, ts.
    Stages: orchestrator_N, meta_eval_N, meta_eval_repair_N_attempt, subagent_<type>, satisfaction_eval, response_builder."""
    return get_invocation_log(_db(), n=n)


@mcp.tool()
def patch_task(task_uuid: str, fields: dict) -> dict:
    """Update a task's fields. Allowed fields: text, status, description, followup_config, position.
    Example: patch_task("uuid", {"status": "done"}) or patch_task("uuid", {"description": "Details..."})"""
    result = patch_task_fields(_db(), task_uuid, fields)
    if result is None:
        return {"error": "Task not found or no valid fields"}
    return result


@mcp.tool()
def append_task_description(task_uuid: str, text: str) -> dict:
    """Append text to a task's description (adds after existing content with double newline).
    Creates description if none exists."""
    db = _db()
    existing = get_task_by_uuid(db, task_uuid)
    if not existing:
        return {"error": "Task not found"}
    current = existing.get("description") or ""
    new_desc = (current + "\n\n" + text).strip() if current else text
    return patch_task_fields(db, task_uuid, {"description": new_desc}) or {"error": "Update failed"}


@mcp.tool()
def search(query: str, type: str = "all") -> list[dict]:
    """Search tasks and milestones by text. Type: 'task', 'milestone', or 'all'.
    Returns [{id, label, sublabel, type}]."""
    return search_entities(_db(), query, type)


@mcp.tool()
def get_task_dependencies(entity_type: str, entity_id: str) -> dict:
    """Get dependencies for a task or milestone. Returns {blocks: [...], blocked_by: [...]}."""
    return get_dependencies_for(_db(), entity_type, entity_id)


@mcp.tool()
def add_task_dependency(blocker_type: str, blocker_id: str, blocked_type: str, blocked_id: str) -> dict:
    """Add a dependency. blocker blocks blocked. Types: 'task' or 'milestone'."""
    dep_id = add_dependency(_db(), blocker_type, blocker_id, blocked_type, blocked_id)
    return {"id": dep_id}


@mcp.tool()
def remove_task_dependency(dep_id: int) -> dict:
    """Remove a dependency by its ID."""
    remove_dependency(_db(), dep_id)
    return {"ok": True}


@mcp.tool()
def get_task_subtasks(task_uuid: str) -> list[dict]:
    """Get subtasks for a task. Returns [{id, task_id, text, done, position}]."""
    return get_subtasks(_db(), task_uuid)


@mcp.tool()
def add_subtask(task_uuid: str, text: str, position: int = 0) -> dict:
    """Add a subtask to a task."""
    return create_subtask(_db(), task_uuid, text, position)


@mcp.tool()
def toggle_subtask(subtask_id: int, done: bool) -> dict:
    """Mark a subtask as done or not done."""
    update_subtask(_db(), subtask_id, done=int(done))
    return {"ok": True}


@mcp.tool()
def remove_subtask(subtask_id: int) -> dict:
    """Delete a subtask."""
    delete_subtask(_db(), subtask_id)
    return {"ok": True}


@mcp.tool()
def unlink_task_from_context(task_uuid: str, subject: str) -> dict:
    """Clear a task's context entry."""
    result = patch_task_fields(_db(), task_uuid, {"context_subject": None})
    if result is None:
        return {"error": f"Task {task_uuid} not found"}
    return {"ok": True}


@mcp.tool()
def get_task_context_links(task_uuid: str) -> list[str]:
    """Get context subject for a task (returns list for backward compat)."""
    task = get_task_by_uuid(_db(), task_uuid)
    if not task:
        return []
    ctx = task.get("context_subject")
    return [ctx] if ctx else []


@mcp.tool()
async def session_done(summary: str = "") -> str:
    """Signal that the current session is complete.

    Call this when you have finished all planned work for this conversation.
    Include a brief summary of what was accomplished — this is saved for
    the user's records and used by the memory management system.

    Args:
        summary: Brief description of what was accomplished in this session.
    """
    return f"Session done acknowledged. Summary: {summary or '(none provided)'}"


# --- Context tree tools ---

# Tree browsing
@mcp.tool()
def list_context_nodes(parent_id: str = "") -> list[dict]:
    """List context nodes. If parent_id is empty, returns root nodes. Otherwise returns children of the given node."""
    from db.queries import get_children
    pid = parent_id if parent_id else None
    return get_children(_db(), pid)


@mcp.tool()
def get_context_node(node_id: str) -> dict:
    """Get a single context node by ID, including section types and children count."""
    from db.queries import get_node
    result = get_node(_db(), node_id)
    if result is None:
        return {"error": f"Node {node_id} not found"}
    return result


@mcp.tool()
def get_node_by_path(path: str) -> dict:
    """Resolve a slash-separated path like 'School/ML/Project' to a node."""
    from db.queries import get_node_by_path as _get
    result = _get(_db(), path)
    if result is None:
        return {"error": f"Path '{path}' not found"}
    return result


# Section-level read/write (token-efficient)
@mcp.tool()
def list_node_sections(node_id: str) -> list[dict]:
    """List section types for a node with file counts per type. Does NOT return body content. Use list_section_files to see individual files, then read_section to get content."""
    from db.queries import get_sections
    sections = get_sections(_db(), node_id)
    grouped: dict[str, dict] = {}
    for s in sections:
        st = s["section_type"]
        if st not in grouped:
            grouped[st] = {"section_type": st, "file_count": 0, "total_size": 0, "updated_at": s["updated_at"]}
        grouped[st]["file_count"] += 1
        grouped[st]["total_size"] += len(s["body"])
        if s["updated_at"] > grouped[st]["updated_at"]:
            grouped[st]["updated_at"] = s["updated_at"]
    return list(grouped.values())


@mcp.tool()
def read_section(node_id: str, section_type: str, name: str = "main") -> dict:
    """Read the full body of a specific section file. Use name='main' (default) for the primary file, or pass a specific name for named files."""
    from db.queries import get_section
    result = get_section(_db(), node_id, section_type, name=name)
    if result is None:
        return {"error": f"Section '{section_type}' file '{name}' not found on node {node_id}"}
    return result


@mcp.tool()
def write_section(node_id: str, section_type: str, body: str, name: str = "main") -> dict:
    """Write (create or replace) a section file on a node. Use name='main' (default) for the primary file, or pass a specific name for named files."""
    import sqlite3
    from db.queries import upsert_section
    try:
        return upsert_section(_db(), node_id, section_type, body, name=name)
    except sqlite3.IntegrityError as e:
        return {"error": f"Write failed: {e}. Check that node_id '{node_id}' exists."}


@mcp.tool()
def append_to_section(node_id: str, section_type: str, content: str, name: str = "main") -> dict:
    """Append text to a section file with a double-newline separator. Creates the section if it doesn't exist. Use name='main' (default) for the primary file, or pass a specific name for named files."""
    import sqlite3
    from db.queries import append_section
    try:
        return append_section(_db(), node_id, section_type, content, name=name)
    except sqlite3.IntegrityError as e:
        return {"error": f"Append failed: {e}. Check that node_id '{node_id}' exists."}


@mcp.tool()
def list_section_files(node_id: str, section_type: str) -> list[dict]:
    """List individual files within a section type. Returns [{name, size, position, updated_at}] without body content — token-efficient for browsing. Use read_section with name param to get a specific file's content."""
    from db.queries import list_section_files as _list_section_files
    return _list_section_files(_db(), node_id, section_type)


@mcp.tool()
def create_section_file(node_id: str, section_type: str, name: str, body: str = "") -> dict:
    """Create a new named file within a section type. Position is auto-assigned. Use write_section with name param to update an existing file."""
    import sqlite3
    from db.queries import create_section_file as _create_section_file
    try:
        return _create_section_file(_db(), node_id, section_type, name, body=body)
    except sqlite3.IntegrityError:
        return {"error": f"Section file '{name}' already exists in '{section_type}'. Use write_section to update it."}


@mcp.tool()
def search_sections(query: str, node_id: str = "") -> list[dict]:
    """Full-text search across all node sections. Returns matching snippets with name field. Optionally scope to a node's subtree."""
    from db.queries import search_sections as _search
    nid = node_id if node_id else None
    return _search(_db(), query, nid)


# Node management
@mcp.tool()
def create_context_node(parent_id: str = "", name: str = "", node_type: str = "context",
                        target_date: str = "", color: str = "") -> dict:
    """Create a new context node or milestone. parent_id empty = root node."""
    from db.queries import create_node
    pid = parent_id if parent_id else None
    kwargs = {}
    if target_date: kwargs["target_date"] = target_date
    if color: kwargs["color"] = color
    return create_node(_db(), pid, name, node_type, **kwargs)


@mcp.tool()
def archive_context_node(node_id: str) -> dict:
    """Archive a node (hides from default views, saves tokens)."""
    from db.queries import archive_node
    archive_node(_db(), node_id)
    return {"ok": True}


@mcp.tool()
def move_context_node(node_id: str, new_parent_id: str = "") -> dict:
    """Move a node to a new parent. Empty new_parent_id = move to root."""
    from db.queries import move_node
    pid = new_parent_id if new_parent_id else None
    move_node(_db(), node_id, pid)
    return {"ok": True}


@mcp.tool()
def patch_context_node(node_id: str, fields: dict) -> dict:
    """Update fields on a context node or milestone.
    Allowed: name, description, node_type, target_date, status, color, archived.
    Returns updated node or error."""
    from db.queries import patch_node_fields, get_node
    result = patch_node_fields(_db(), node_id, fields)
    if result is None:
        return {"error": f"Node {node_id} not found or no valid fields"}
    return get_node(_db(), node_id)


# Task linking (new system)
@mcp.tool()
def link_task_to_node(task_id: str, node_id: str) -> dict:
    """Link a task to a context node or milestone."""
    from db.queries import link_task_to_node as _link
    _link(_db(), node_id, task_id)
    return {"ok": True}


@mcp.tool()
def unlink_task_from_node(task_id: str, node_id: str) -> dict:
    """Unlink a task from a context node or milestone."""
    from db.queries import unlink_task_from_node as _unlink
    _unlink(_db(), node_id, task_id)
    return {"ok": True}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sse", action="store_true", help="Run as SSE server (for network access)")
    args = parser.parse_args()
    mcp.run(transport="sse" if args.sse else "stdio")
