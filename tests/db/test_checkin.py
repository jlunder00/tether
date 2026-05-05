import pytest
try:
    from db.schema import init_db
    from db.queries import upsert_anchor, upsert_plan, get_plan, insert_check_in
except ImportError:
    pytestmark = pytest.mark.skip(reason="Skipping as Sqlite DB is deprecated and the required imports have been removed. Ensure Postgres equivalents are tested prior to removing these tests")


def test_insert_check_in_appears_in_plan(tmp_path):
    db_path = tmp_path / "tether.db"
    init_db(db_path)
    upsert_anchor(db_path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                             "duration_minutes": 120, "flexibility": "locked",
                             "strictness": 4, "color": "#e05c5c", "position": 0})
    upsert_plan(db_path, "2026-03-26")
    insert_check_in(db_path, "2026-03-26", "grind_am",
                    accomplished="Applied to 2 jobs", current_status="About to start third")
    plan = get_plan(db_path, "2026-03-26")
    assert len(plan["check_in_log"]) == 1
    entry = plan["check_in_log"][0]
    assert entry["anchor_id"] == "grind_am"
    assert entry["accomplished"] == "Applied to 2 jobs"
    assert entry["type"] == "user_checkin"
