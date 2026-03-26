from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from bot.plan_reader import AnchorPlan, DayPlan


def build_anchor_prompt(
    templates_dir: Path,
    anchor_id: str,
    anchor_name: str,
    anchor_plan: AnchorPlan,
    day_plan: DayPlan,
    context: str,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("anchor_message.md")
    return template.render(
        anchor_id=anchor_id,
        anchor_name=anchor_name,
        tasks=anchor_plan.tasks,
        notes=anchor_plan.notes,
        context=context,
        acknowledgements=day_plan.acknowledgements,
        check_in_log=day_plan.check_in_log,
    )
