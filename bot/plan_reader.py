from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path


@dataclass
class AnchorPlan:
    tasks: list = field(default_factory=list)  # list[str] from YAML, list[dict] from DB
    notes: str = ""


@dataclass
class DayPlan:
    date: str
    anchors: dict[str, AnchorPlan]
    acknowledgements: dict[str, str]
    check_in_log: list[dict]


def load_plan(config_dir: Path) -> DayPlan:
    db_path = config_dir / "tether.db"
    if db_path.exists():
        return _load_plan_from_db(db_path)
    return _load_plan_from_yaml(config_dir)


def load_context(config_dir: Path) -> str:
    db_path = config_dir / "tether.db"
    if db_path.exists():
        return _load_context_from_db(db_path)
    context_path = config_dir / "context.md"
    if not context_path.exists():
        return ""
    return context_path.read_text()


def _load_plan_from_db(db_path: Path) -> DayPlan:
    from db.queries import get_plan
    today = str(date_type.today())
    data = get_plan(db_path, today)
    anchors = {
        k: AnchorPlan(tasks=v.get("tasks", []), notes=v.get("notes", "") or "")
        for k, v in data["anchors"].items()
    }
    return DayPlan(
        date=data["date"],
        anchors=anchors,
        acknowledgements=data["acknowledgements"],
        check_in_log=data["check_in_log"],
    )


def _load_plan_from_yaml(config_dir: Path) -> DayPlan:
    with open(config_dir / "plan.yaml") as f:
        data = yaml.safe_load(f)
    anchors = {
        k: AnchorPlan(tasks=v.get("tasks", []), notes=v.get("notes", "") or "")
        for k, v in data.get("anchors", {}).items()
    }
    return DayPlan(
        date=str(data["date"]),
        anchors=anchors,
        acknowledgements=data.get("acknowledgements", {}),
        check_in_log=data.get("check_in_log", []),
    )


def _load_context_from_db(db_path: Path) -> str:
    from db.queries import get_context_entries
    entries = get_context_entries(db_path)
    if not entries:
        return ""
    return "\n\n".join(f"## {e['subject']}\n{e['body']}" for e in entries)
