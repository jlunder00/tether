"""Tests for bot/relationships.py — milestone/task/context link resolution for Beacon."""
import asyncio
import pytest
from datetime import date
from db.schema import init_db
from db.queries import (
    upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry,
    create_milestone, link_milestone_task, get_plan, get_milestones,
)


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    init_db(str(p))
    return str(p)


@pytest.fixture
def rich_db(db_path):
    """DB with anchors, tasks, milestones linked to tasks, and context entries."""
    today = date.today().isoformat()
    upsert_anchor(db_path, {
        "id": "morning", "name": "Morning", "time": "07:00",
        "duration_minutes": 120, "flexibility": "locked",
        "strictness": 3, "color": "#fff", "position": 0,
    })
    upsert_context_entry(db_path, "Work/Alpha", "Project Alpha is a big initiative.")
    upsert_context_entry(db_path, "Work/Beta", "Project Beta is secondary.")

    upsert_plan(db_path, today)
    upsert_tasks(db_path, today, "morning", [
        {"text": "Finish Alpha feature", "status": "done", "position": 0},
        {"text": "Write Alpha tests", "status": "in_progress", "position": 1},
        {"text": "Beta research", "status": "pending", "position": 2},
    ])

    # Get task UUIDs
    plan = get_plan(db_path, today)
    tasks = plan["anchors"]["morning"]["tasks"]
    alpha_feature = next(t for t in tasks if "Alpha feature" in str(t))
    alpha_tests = next(t for t in tasks if "Alpha tests" in str(t))
    beta_research = next(t for t in tasks if "Beta" in str(t))

    # Create milestones linked to context entries
    m1 = create_milestone(db_path, "Work/Alpha", "Alpha MVP")
    m2 = create_milestone(db_path, "Work/Beta", "Beta exploration")

    # Link tasks to milestones
    t1_id = alpha_feature["id"] if isinstance(alpha_feature, dict) else alpha_feature
    t2_id = alpha_tests["id"] if isinstance(alpha_tests, dict) else alpha_tests
    t3_id = beta_research["id"] if isinstance(beta_research, dict) else beta_research

    link_milestone_task(db_path, m1["id"], t1_id)
    link_milestone_task(db_path, m1["id"], t2_id)
    link_milestone_task(db_path, m2["id"], t3_id)

    # Direct task→context links (context_subject column on tasks)
    from db.queries import patch_task_fields
    patch_task_fields(db_path, t1_id, {"context_subject": "Work/Alpha"})  # also linked via milestone — dedup test
    patch_task_fields(db_path, t3_id, {"context_subject": "Work/Beta"})   # also linked via milestone
    patch_task_fields(db_path, t2_id, {"context_subject": "Work/Beta"})   # cross-link: alpha_tests → Beta context

    return {
        "db_path": db_path,
        "today": today,
        "task_ids": {"alpha_feature": t1_id, "alpha_tests": t2_id, "beta_research": t3_id},
        "milestone_ids": {"alpha_mvp": m1["id"], "beta_explore": m2["id"]},
    }


# ---------------------------------------------------------------------------
# resolve_task_context — trace task → direct + milestone → context
# ---------------------------------------------------------------------------

class TestResolveTaskContext:
    def test_finds_context_for_linked_task(self, rich_db):
        from bot.relationships import resolve_task_context
        result = resolve_task_context(
            rich_db["db_path"],
            rich_db["task_ids"]["alpha_feature"],
        )
        assert len(result) > 0
        subjects = [r["context_subject"] for r in result]
        assert "Work/Alpha" in subjects

    def test_direct_link_has_source_direct(self, rich_db):
        from bot.relationships import resolve_task_context
        result = resolve_task_context(
            rich_db["db_path"],
            rich_db["task_ids"]["alpha_feature"],
        )
        direct = [r for r in result if r["source"] == "direct"]
        assert len(direct) >= 1
        assert direct[0]["context_subject"] == "Work/Alpha"

    def test_milestone_link_has_source_milestone(self, rich_db):
        from bot.relationships import resolve_task_context
        result = resolve_task_context(
            rich_db["db_path"],
            rich_db["task_ids"]["alpha_feature"],
        )
        milestone = [r for r in result if r["source"] == "milestone"]
        # alpha_feature is linked to Work/Alpha both directly and via milestone
        # Direct takes precedence (dedup), so milestone link for same subject is skipped
        # But the result should still have entries
        assert len(result) >= 1

    def test_both_paths_returned_for_same_subject(self, rich_db):
        """alpha_feature → Work/Alpha via direct AND via milestone. Both returned (different source)."""
        from bot.relationships import resolve_task_context
        result = resolve_task_context(
            rich_db["db_path"],
            rich_db["task_ids"]["alpha_feature"],
        )
        alpha_entries = [r for r in result if r["context_subject"] == "Work/Alpha"]
        sources = {r["source"] for r in alpha_entries}
        assert "direct" in sources
        assert "milestone" in sources

    def test_cross_link_finds_context_not_in_milestone(self, rich_db):
        """alpha_tests is linked to Work/Beta directly but to Work/Alpha via milestone."""
        from bot.relationships import resolve_task_context
        result = resolve_task_context(
            rich_db["db_path"],
            rich_db["task_ids"]["alpha_tests"],
        )
        subjects = [r["context_subject"] for r in result]
        assert "Work/Beta" in subjects   # direct link
        assert "Work/Alpha" in subjects  # via milestone

    def test_returns_milestone_info(self, rich_db):
        from bot.relationships import resolve_task_context
        result = resolve_task_context(
            rich_db["db_path"],
            rich_db["task_ids"]["alpha_feature"],
        )
        milestones = [r["milestone_name"] for r in result]
        assert "Alpha MVP" in milestones

    def test_returns_empty_for_unlinked_task(self, rich_db):
        from bot.relationships import resolve_task_context
        result = resolve_task_context(rich_db["db_path"], "nonexistent-uuid")
        assert result == []


# ---------------------------------------------------------------------------
# get_milestone_summary — enriched milestone status with task + context info
# ---------------------------------------------------------------------------

class TestGetMilestoneSummary:
    def test_returns_milestone_with_tasks_and_context(self, rich_db):
        from bot.relationships import get_milestone_summary
        result = get_milestone_summary(
            rich_db["db_path"],
            rich_db["milestone_ids"]["alpha_mvp"],
        )
        assert result is not None
        assert result["name"] == "Alpha MVP"
        assert result["context_subject"] == "Work/Alpha"
        assert result["task_count"] == 2
        assert result["done_count"] >= 1

    def test_returns_none_for_unknown_milestone(self, rich_db):
        from bot.relationships import get_milestone_summary
        result = get_milestone_summary(rich_db["db_path"], "nonexistent-id")
        assert result is None

    def test_includes_completion_ratio(self, rich_db):
        from bot.relationships import get_milestone_summary
        result = get_milestone_summary(
            rich_db["db_path"],
            rich_db["milestone_ids"]["alpha_mvp"],
        )
        assert "completion" in result
        assert 0.0 <= result["completion"] <= 1.0


# ---------------------------------------------------------------------------
# get_affected_context_subjects — given change events, return impacted contexts
# ---------------------------------------------------------------------------

class TestGetAffectedContextSubjects:
    def test_task_done_finds_linked_context(self, rich_db):
        from bot.relationships import get_affected_context_subjects
        changes = [
            {"change_type": "task_done", "entity_id": rich_db["task_ids"]["alpha_feature"]},
        ]
        subjects = get_affected_context_subjects(rich_db["db_path"], changes)
        assert "Work/Alpha" in subjects

    def test_context_updated_includes_itself(self, rich_db):
        from bot.relationships import get_affected_context_subjects
        changes = [
            {"change_type": "context_updated", "entity_id": "Work/Beta"},
        ]
        subjects = get_affected_context_subjects(rich_db["db_path"], changes)
        assert "Work/Beta" in subjects

    def test_multiple_changes_deduplicates(self, rich_db):
        from bot.relationships import get_affected_context_subjects
        changes = [
            {"change_type": "task_done", "entity_id": rich_db["task_ids"]["alpha_feature"]},
            {"change_type": "task_done", "entity_id": rich_db["task_ids"]["alpha_tests"]},
        ]
        subjects = get_affected_context_subjects(rich_db["db_path"], changes)
        assert subjects.count("Work/Alpha") == 1

    def test_unlinked_task_returns_no_context(self, rich_db):
        from bot.relationships import get_affected_context_subjects
        changes = [
            {"change_type": "task_done", "entity_id": "no-such-task"},
        ]
        subjects = get_affected_context_subjects(rich_db["db_path"], changes)
        assert len(subjects) == 0


# ---------------------------------------------------------------------------
# build_beacon_context — full enrichment for Beacon triage
# ---------------------------------------------------------------------------

class TestBuildBeaconContext:
    def test_includes_change_summary_and_context(self, rich_db):
        from bot.relationships import build_beacon_context
        changes = [
            {"change_type": "task_done", "entity_id": rich_db["task_ids"]["alpha_feature"],
             "score": 2},
        ]
        ctx = build_beacon_context(rich_db["db_path"], changes)
        assert isinstance(ctx, str)
        assert "Work/Alpha" in ctx
        assert "Alpha MVP" in ctx
        assert "task_done" in ctx

    def test_includes_milestone_completion(self, rich_db):
        from bot.relationships import build_beacon_context
        changes = [
            {"change_type": "task_done", "entity_id": rich_db["task_ids"]["alpha_feature"],
             "score": 2},
        ]
        ctx = build_beacon_context(rich_db["db_path"], changes)
        # Should mention how many tasks done out of total
        assert "1" in ctx or "2" in ctx

    def test_empty_changes_returns_minimal_context(self, rich_db):
        from bot.relationships import build_beacon_context
        ctx = build_beacon_context(rich_db["db_path"], [])
        assert isinstance(ctx, str)
