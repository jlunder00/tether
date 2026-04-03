from __future__ import annotations
import json
import os
from datetime import date as date_type, datetime
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from db.queries import (
    get_anchors as _db_get_anchors,
    get_context_entries,
    get_invocation_log,
    get_plan,
    upsert_context_entry,
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
    unlink_milestone_task,
    create_milestone,
    link_task_context,
    unlink_task_context,
    get_task_contexts,
    get_context_tasks,
    patch_milestone,
)

mcp = FastMCP("tether", host="0.0.0.0", port=5001)


def _db() -> Path:
    env = os.environ.get("TETHER_DB_PATH")
    if env:
        return Path(env)
    user_id = os.environ.get("TETHER_USER_ID")
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

def _list_context_entries(prefix: str = "") -> list[dict]:
    if prefix:
        return get_context_entries(_db(), prefix=prefix)
    entries = get_context_entries(_db(), top_level_only=True)
    all_subjects = {e["subject"] for e in get_context_entries(_db())}
    for e in entries:
        e["has_children"] = any(s.startswith(e["subject"] + "/") for s in all_subjects)
    return entries


def _get_context_entry(subject: str) -> dict:
    entries = get_context_entries(_db())
    match = next((e for e in entries if e["subject"] == subject), None)
    if not match:
        raise ValueError(f"No context entry found for subject: {subject!r}")
    return match


def _update_context_entry(subject: str, body: str) -> dict:
    upsert_context_entry(_db(), subject, body)
    return {"ok": True}


def _append_context_entry(subject: str, content: str) -> dict:
    entries = get_context_entries(_db())
    entry = next((e for e in entries if e["subject"] == subject), None)
    current = entry["body"] if entry else ""
    upsert_context_entry(_db(), subject, current.rstrip() + "\n\n" + content)
    return {"ok": True}


def _patch_context_entry(subject: str, old: str, new: str) -> dict:
    entries = get_context_entries(_db())
    entry = next((e for e in entries if e["subject"] == subject), None)
    if not entry:
        raise ValueError(f"No context entry found for subject: {subject!r}")
    if old not in entry["body"]:
        raise ValueError(f"Text not found in {subject!r}: {old[:60]!r}")
    upsert_context_entry(_db(), subject, entry["body"].replace(old, new, 1))
    return {"ok": True}


def _get_today_plan(date: str | None = None) -> dict:
    d = date or str(date_type.today())
    return get_plan(_db(), d)


def _update_plan_tasks(anchor_id: str, tasks: list[str], date: str | None = None) -> list[dict]:
    d = date or str(date_type.today())
    upsert_plan(_db(), d)
    return upsert_tasks(_db(), d, anchor_id, tasks, notes="")


def _get_anchors() -> list[dict]:
    return _db_get_anchors(_db())


def _get_current_anchor() -> dict:
    return _current_anchor(_db_get_anchors(_db()))


# --- MCP tool wrappers ---

@mcp.tool()
def list_context_entries(prefix: str = "") -> list[dict]:
    """List context entries. No prefix: returns top-level only with has_children flag.
    Pass prefix (e.g. 'Intellipat') to get full subtree including all children."""
    return _list_context_entries(prefix)


@mcp.tool()
def get_context_entry(subject: str) -> dict:
    """Get a single context entry by exact subject path (e.g. 'Intellipat/Backend')."""
    return _get_context_entry(subject)


@mcp.tool()
def update_context_entry(subject: str, body: str) -> dict:
    """Full rewrite of a context entry. Use only for large structural changes. For adding or correcting small sections, prefer append_context_entry or patch_context_entry instead. IMPORTANT: always call list_context_entries first and match against existing subjects."""
    return _update_context_entry(subject, body)


@mcp.tool()
def append_context_entry(subject: str, content: str) -> dict:
    """Append new content to the end of an existing context entry. Creates the entry if it doesn't exist. Preferred over update_context_entry for adding new information."""
    return _append_context_entry(subject, content)


@mcp.tool()
def patch_context_entry(subject: str, old: str, new: str) -> dict:
    """Find-and-replace within a context entry body. Pass the exact text to replace as `old` and the replacement as `new`. Set new='' to delete a section. Raises if `old` is not found."""
    return _patch_context_entry(subject, old, new)


@mcp.tool()
def get_today_plan(date: str = "") -> dict:
    """Get the anchor plan for a given date. Pass YYYY-MM-DD or leave empty for today."""
    return _get_today_plan(date or None)


@mcp.tool()
def update_plan_tasks(anchor_id: str, tasks: list[str], date: str = "") -> dict:
    """Replace the task list for an anchor. Pass YYYY-MM-DD or leave empty for today."""
    return _update_plan_tasks(anchor_id, tasks, date or None)


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
async def get_milestones(context_subject: str | None = None) -> str:
    """Get milestones for a context subject (or all if omitted).
    Returns list with id, name, status, task_count, done_count, task_ids."""
    from db.queries import get_milestones as _get_milestones
    return json.dumps(_get_milestones(_db(), context_subject), indent=2)


@mcp.tool()
def patch_task(task_uuid: str, fields: dict) -> dict:
    """Update a task's fields. Allowed fields: text, status, description, followup_config, position.
    Example: patch_task("uuid", {"status": "done"}) or patch_task("uuid", {"description": "Details..."})"""
    result = patch_task_fields(_db(), task_uuid, fields)
    if result is None:
        return {"error": "Task not found or no valid fields"}
    return result


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
def link_task_to_milestone(milestone_id: str, task_id: str) -> dict:
    """Link a task to a milestone."""
    link_milestone_task(_db(), milestone_id, task_id)
    return {"ok": True}


@mcp.tool()
def unlink_task_from_milestone(milestone_id: str, task_id: str) -> dict:
    """Unlink a task from a milestone."""
    unlink_milestone_task(_db(), milestone_id, task_id)
    return {"ok": True}


@mcp.tool()
def create_new_milestone(context_subject: str, name: str, description: str = "", target_date: str = "") -> dict:
    """Create a milestone under a context subject. Returns the new milestone dict."""
    return create_milestone(_db(), context_subject, name,
                            description or None, target_date or None)


@mcp.tool()
def update_milestone(milestone_id: str, fields: dict) -> dict:
    """Update a milestone. Allowed fields: name, description, target_date, status.
    Setting status also sets status_override=true."""
    result = patch_milestone(_db(), milestone_id, fields)
    if result is None:
        return {"error": "Milestone not found or no valid fields"}
    return result


@mcp.tool()
def link_task_to_context(task_uuid: str, subject: str) -> dict:
    """Link a task to a context entry by subject."""
    link_task_context(_db(), task_uuid, subject)
    return {"ok": True}


@mcp.tool()
def unlink_task_from_context(task_uuid: str, subject: str) -> dict:
    """Unlink a task from a context entry."""
    unlink_task_context(_db(), task_uuid, subject)
    return {"ok": True}


@mcp.tool()
def get_task_context_links(task_uuid: str) -> list[str]:
    """Get context subjects linked to a task."""
    return get_task_contexts(_db(), task_uuid)


@mcp.tool()
def get_context_linked_tasks(subject: str) -> list[dict]:
    """Get tasks linked to a context entry. Returns [{uuid, text, status, plan_date, anchor_id}]."""
    return get_context_tasks(_db(), subject)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sse", action="store_true", help="Run as SSE server (for network access)")
    args = parser.parse_args()
    mcp.run(transport="sse" if args.sse else "stdio")
