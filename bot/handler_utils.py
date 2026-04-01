from __future__ import annotations
from datetime import datetime
from typing import Optional


def parse_check_in(text: str) -> tuple[str, str]:
    body = text.removeprefix("/check-in").strip()
    if "::" in body:
        accomplished, _, status = body.partition("::")
        return accomplished.strip(), status.strip()
    return body, ""


def parse_update_context(text: str) -> tuple[str, str]:
    body = text.removeprefix("/tether-update-context").strip()
    if "::" not in body:
        raise ValueError(f"Missing '::' separator in: {text!r}")
    subject, _, content = body.partition("::")
    return subject.strip(), content.strip()


def parse_update_plan(text: str) -> tuple[str, list[str]]:
    body = text.removeprefix("/update-plan").strip()
    anchor_id, _, tasks_raw = body.partition("::")
    tasks = [t.strip() for t in tasks_raw.split(";") if t.strip()]
    return anchor_id.strip(), tasks


def is_anchor_active(anchor: dict, now: Optional[datetime] = None) -> bool:
    """Return True if `now` falls within [anchor_start, anchor_start + duration]."""
    if now is None:
        now = datetime.now()
    today = now.date()
    h, m = map(int, anchor["time"].split(":"))
    start = datetime(today.year, today.month, today.day, h, m)
    from datetime import timedelta
    end = start + timedelta(minutes=anchor.get("duration_minutes", 0))
    return start <= now < end


def get_current_anchor(anchors: list[dict], now: Optional[datetime] = None) -> dict:
    """Return the anchor whose time window contains `now`.

    If before first anchor, returns first. If after last, returns last.
    """
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
