from __future__ import annotations
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
)

mcp = FastMCP("tether", host="0.0.0.0", port=5001)


def _db() -> Path:
    env = os.environ.get("TETHER_DB_PATH")
    if env:
        return Path(env)
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


def _update_plan_tasks(anchor_id: str, tasks: list[str], date: str | None = None) -> dict:
    d = date or str(date_type.today())
    upsert_plan(_db(), d)
    upsert_tasks(_db(), d, anchor_id, tasks, notes="")
    return {"ok": True}


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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sse", action="store_true", help="Run as SSE server (for network access)")
    args = parser.parse_args()
    mcp.run(transport="sse" if args.sse else "stdio")
