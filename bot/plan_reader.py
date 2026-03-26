from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AnchorPlan:
    tasks: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class DayPlan:
    date: str
    anchors: dict[str, AnchorPlan]
    acknowledgements: dict[str, str]
    check_in_log: list[dict]


def load_plan(config_dir: Path) -> DayPlan:
    with open(config_dir / "plan.yaml") as f:
        data = yaml.safe_load(f)
    anchors = {
        k: AnchorPlan(
            tasks=v.get("tasks", []),
            notes=v.get("notes", "") or "",
        )
        for k, v in data.get("anchors", {}).items()
    }
    return DayPlan(
        date=str(data["date"]),
        anchors=anchors,
        acknowledgements=data.get("acknowledgements", {}),
        check_in_log=data.get("check_in_log", []),
    )


def load_context(config_dir: Path) -> str:
    context_path = config_dir / "context.md"
    if not context_path.exists():
        return ""
    return context_path.read_text()
