import pytest
from pathlib import Path
from bot.plan_reader import AnchorPlan, DayPlan
from bot.prompt_builder import build_anchor_prompt


@pytest.fixture
def templates_dir(tmp_path):
    (tmp_path / "anchor_message.md").write_text(
        "Anchor: {{ anchor_name }}\n"
        "Tasks:\n{% for t in tasks %}- {{ t }}\n{% endfor %}"
        "{% if notes %}Notes: {{ notes }}\n{% endif %}"
        "{% if context %}Context: {{ context }}{% endif %}"
    )
    return tmp_path


@pytest.fixture
def empty_plan():
    return DayPlan(date="2026-03-25", anchors={}, acknowledgements={}, check_in_log=[])


def test_prompt_contains_anchor_name(templates_dir, empty_plan):
    anchor_plan = AnchorPlan(tasks=["Apply to jobs"])
    result = build_anchor_prompt(
        templates_dir=templates_dir,
        anchor_id="grind_am",
        anchor_name="The Grind",
        anchor_plan=anchor_plan,
        day_plan=empty_plan,
        context="",
    )
    assert "The Grind" in result


def test_prompt_contains_all_tasks(templates_dir, empty_plan):
    anchor_plan = AnchorPlan(tasks=["Apply to 3 jobs", "Follow up on Stripe"])
    result = build_anchor_prompt(
        templates_dir=templates_dir,
        anchor_id="grind_am",
        anchor_name="The Grind",
        anchor_plan=anchor_plan,
        day_plan=empty_plan,
        context="",
    )
    assert "Apply to 3 jobs" in result
    assert "Follow up on Stripe" in result


def test_prompt_contains_notes_when_present(templates_dir, empty_plan):
    anchor_plan = AnchorPlan(tasks=[], notes="ML roles only")
    result = build_anchor_prompt(
        templates_dir=templates_dir,
        anchor_id="grind_am",
        anchor_name="The Grind",
        anchor_plan=anchor_plan,
        day_plan=empty_plan,
        context="",
    )
    assert "ML roles only" in result


def test_prompt_omits_notes_when_empty(templates_dir, empty_plan):
    anchor_plan = AnchorPlan(tasks=[], notes="")
    result = build_anchor_prompt(
        templates_dir=templates_dir,
        anchor_id="grind_am",
        anchor_name="The Grind",
        anchor_plan=anchor_plan,
        day_plan=empty_plan,
        context="",
    )
    assert "Notes:" not in result


def test_prompt_contains_context(templates_dir, empty_plan):
    anchor_plan = AnchorPlan(tasks=[])
    result = build_anchor_prompt(
        templates_dir=templates_dir,
        anchor_id="grind_am",
        anchor_name="The Grind",
        anchor_plan=anchor_plan,
        day_plan=empty_plan,
        context="Job search is priority 1",
    )
    assert "Job search is priority 1" in result
