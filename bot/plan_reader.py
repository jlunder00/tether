from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type


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


async def load_plan(pool, user_id: str) -> DayPlan:
    import db.postgres as pg
    from db.pg_queries import plans as plans_module

    today = str(date_type.today())
    async with pg.get_conn(pool, user_id) as conn:
        data = await plans_module.get_plan(conn, today)
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


async def load_context(pool, user_id: str) -> str:
    import db.postgres as pg
    from db.pg_queries import nodes as nodes_module
    from db.pg_queries import sections as sections_module

    async with pg.get_conn(pool, user_id) as conn:
        root_nodes = await nodes_module.get_children(conn, parent_id=None)
        if not root_nodes:
            return ""
        parts = []
        for node in root_nodes:
            path = await nodes_module.get_node_path(conn, node["id"]) or node["name"]
            sec = await sections_module.get_section(conn, node["id"], "details")
            body = sec["body"] if sec else ""
            parts.append(f"## {path}\n{body}")
    return "\n\n".join(parts)
