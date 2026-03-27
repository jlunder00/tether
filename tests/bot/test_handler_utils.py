import pytest
from datetime import datetime
from bot.handler_utils import (
    parse_check_in,
    parse_update_context,
    parse_update_plan,
    get_current_anchor,
)


def test_parse_check_in_splits_on_separator():
    accomplished, status = parse_check_in("/check-in finished 3 apps :: now on interview prep")
    assert accomplished == "finished 3 apps"
    assert status == "now on interview prep"


def test_parse_check_in_no_separator_returns_text_and_empty():
    accomplished, status = parse_check_in("/check-in working on thesis")
    assert accomplished == "working on thesis"
    assert status == ""


def test_parse_update_context_splits_subject_and_body():
    subject, body = parse_update_context("/tether-update-context Job Applications :: Applying for ML roles")
    assert subject == "Job Applications"
    assert body == "Applying for ML roles"


def test_parse_update_context_missing_separator_raises():
    with pytest.raises(ValueError):
        parse_update_context("/tether-update-context no separator here")


def test_parse_update_plan_returns_anchor_and_tasks():
    anchor_id, tasks = parse_update_plan("/update-plan grind_am :: Apply to 3 jobs; Follow up Stripe")
    assert anchor_id == "grind_am"
    assert tasks == ["Apply to 3 jobs", "Follow up Stripe"]


def test_get_current_anchor_returns_active_anchor():
    anchors = [
        {"id": "launch_pad",  "time": "07:00", "duration_minutes": 60},
        {"id": "grind_am",    "time": "08:00", "duration_minutes": 120},
        {"id": "deep_work",   "time": "10:30", "duration_minutes": 120},
    ]
    now = datetime(2026, 3, 26, 9, 15)
    anchor = get_current_anchor(anchors, now=now)
    assert anchor["id"] == "grind_am"


def test_get_current_anchor_before_first_anchor_returns_first():
    anchors = [{"id": "launch_pad", "time": "07:00", "duration_minutes": 60}]
    now = datetime(2026, 3, 26, 6, 0)
    anchor = get_current_anchor(anchors, now=now)
    assert anchor["id"] == "launch_pad"


def test_get_current_anchor_after_last_anchor_returns_last():
    anchors = [
        {"id": "grind_am",  "time": "08:00", "duration_minutes": 120},
        {"id": "wind_down", "time": "21:00", "duration_minutes": 60},
    ]
    now = datetime(2026, 3, 26, 23, 0)
    anchor = get_current_anchor(anchors, now=now)
    assert anchor["id"] == "wind_down"
