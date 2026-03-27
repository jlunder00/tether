from __future__ import annotations
import os
from datetime import date as date_type, datetime
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from db.queries import (
    get_anchors as _db_get_anchors,
    get_context_entries,
    get_plan,
    upsert_context_entry,
    upsert_plan,
    upsert_tasks,
)

mcp = FastMCP("tether")


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

def _list_context_entries() -> list[dict]:
    return get_context_entries(_db())


def _update_context_entry(subject: str, body: str) -> dict:
    upsert_context_entry(_db(), subject, body)
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
def list_context_entries() -> list[dict]:
    """List all context entries (subject + body) from the Tether DB."""
    return _list_context_entries()


@mcp.tool()
def update_context_entry(subject: str, body: str) -> dict:
    """Create or update a context entry by subject. IMPORTANT: always call list_context_entries first and match against existing subjects before writing. Reuse an existing subject rather than creating a near-duplicate (e.g. 'Job Applications' not 'Job Search'). Only create a new subject if nothing existing is a reasonable match."""
    return _update_context_entry(subject, body)


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


if __name__ == "__main__":
    mcp.run()
