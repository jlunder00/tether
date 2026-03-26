import pytest
import yaml
from bot.plan_reader import load_plan, load_context, DayPlan, AnchorPlan


@pytest.fixture
def config_dir(tmp_path):
    plan = {
        "date": "2026-03-25",
        "anchors": {
            "grind_am": {
                "tasks": ["Apply to 3 jobs", "Follow up email"],
                "notes": "Focus: ML roles",
            },
            "deep_work": {
                "tasks": ["Thesis section 3.2"],
                "notes": "",
            },
        },
        "acknowledgements": {},
        "check_in_log": [],
    }
    (tmp_path / "plan.yaml").write_text(yaml.dump(plan))
    (tmp_path / "context.md").write_text("# Projects\nJob search is priority 1.")
    return tmp_path


def test_load_plan_reads_date(config_dir):
    plan = load_plan(config_dir)
    assert plan.date == "2026-03-25"


def test_load_plan_reads_anchor_tasks(config_dir):
    plan = load_plan(config_dir)
    assert "grind_am" in plan.anchors
    assert plan.anchors["grind_am"].tasks == ["Apply to 3 jobs", "Follow up email"]


def test_load_plan_reads_notes(config_dir):
    plan = load_plan(config_dir)
    assert plan.anchors["grind_am"].notes == "Focus: ML roles"


def test_load_plan_multiple_anchors(config_dir):
    plan = load_plan(config_dir)
    assert "deep_work" in plan.anchors
    assert plan.anchors["deep_work"].tasks == ["Thesis section 3.2"]


def test_load_plan_acknowledgements_empty_by_default(config_dir):
    plan = load_plan(config_dir)
    assert plan.acknowledgements == {}


def test_load_plan_check_in_log_empty_by_default(config_dir):
    plan = load_plan(config_dir)
    assert plan.check_in_log == []


def test_load_context_reads_file(config_dir):
    context = load_context(config_dir)
    assert "Job search is priority 1" in context


def test_load_context_returns_empty_string_if_missing(tmp_path):
    context = load_context(tmp_path)
    assert context == ""
