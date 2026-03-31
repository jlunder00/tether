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


from datetime import date as date_type
from db.schema import init_db
from db.queries import upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry


@pytest.fixture
def db_config_dir(tmp_path):
    today = str(date_type.today())
    db_path = tmp_path / "tether.db"
    init_db(db_path)
    upsert_anchor(db_path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                             "duration_minutes": 120, "flexibility": "locked",
                             "strictness": 4, "color": "#e05c5c", "position": 0})
    upsert_plan(db_path, today)
    upsert_tasks(db_path, today, "grind_am",
                 tasks=["Apply to 3 jobs", "Follow up"], notes="ML roles")
    upsert_context_entry(db_path, "Job Applications", "Priority 1.")
    return tmp_path


def test_load_plan_from_db(db_config_dir):
    plan = load_plan(db_config_dir)
    assert "grind_am" in plan.anchors
    texts = [t["text"] for t in plan.anchors["grind_am"].tasks]
    assert texts == ["Apply to 3 jobs", "Follow up"]


def test_load_context_from_db_concatenates_entries(db_config_dir):
    context = load_context(db_config_dir)
    assert "Priority 1." in context
