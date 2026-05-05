"""Tests for context_subject migration onto the tasks table."""
import pytest
from pathlib import Path
try:
    from db.schema import init_db
    from db.queries import (
        upsert_plan,
        upsert_tasks,
        get_plan,
        patch_task_fields,
        get_task_by_uuid,
        create_unscheduled_task,
        get_unscheduled_tasks,
        upsert_context_entry,
    )
except ImportError:
    pytestmark = pytest.mark.skip(reason="Skipping as Sqlite DB is deprecated and the required imports have been removed. Ensure Postgres equivalents are tested prior to removing these tests")

@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


# ---------------------------------------------------------------------------
# create_unscheduled_task: context_subject param
# ---------------------------------------------------------------------------

def test_create_unscheduled_task_with_context_subject(db_path):
    task = create_unscheduled_task(db_path, "Fix login bug", context_subject="Backend")
    assert task["context_subject"] == "Backend"
    assert task["id"] is not None


def test_create_unscheduled_task_without_context_subject(db_path):
    task = create_unscheduled_task(db_path, "Some task")
    assert task["context_subject"] is None


# ---------------------------------------------------------------------------
# get_unscheduled_tasks: returns context_subject directly (no JOIN)
# ---------------------------------------------------------------------------

def test_get_unscheduled_tasks_returns_context_subject(db_path):
    create_unscheduled_task(db_path, "Task A", context_subject="Tether")
    create_unscheduled_task(db_path, "Task B", context_subject=None)

    tasks = get_unscheduled_tasks(db_path)
    by_text = {t["text"]: t for t in tasks}

    assert by_text["Task A"]["context_subject"] == "Tether"
    assert by_text["Task B"]["context_subject"] is None


def test_get_unscheduled_tasks_no_contexts_key(db_path):
    """The old 'contexts' key should not appear — only context_subject."""
    create_unscheduled_task(db_path, "Task X")
    tasks = get_unscheduled_tasks(db_path)
    for task in tasks:
        assert "contexts" not in task
        assert "context_subject" in task


# ---------------------------------------------------------------------------
# get_plan: returns context_subject on tasks
# ---------------------------------------------------------------------------

def test_get_plan_returns_context_subject(db_path):
    upsert_plan(db_path, "2026-04-11")
    upsert_tasks(db_path, "2026-04-11", "morning", [
        {"text": "Deploy API", "context_subject": "Tether"},
        {"text": "Review PR"},
    ])
    plan = get_plan(db_path, "2026-04-11")
    tasks = plan["anchors"]["morning"]["tasks"]
    by_text = {t["text"]: t for t in tasks}

    assert by_text["Deploy API"]["context_subject"] == "Tether"
    assert by_text["Review PR"]["context_subject"] is None


# ---------------------------------------------------------------------------
# patch_task_fields: can set and clear context_subject
# ---------------------------------------------------------------------------

def test_patch_task_fields_set_context_subject(db_path):
    task = create_unscheduled_task(db_path, "Do something")
    result = patch_task_fields(db_path, task["id"], {"context_subject": "Job Applications"})
    assert result is not None
    assert result["context_subject"] == "Job Applications"


def test_patch_task_fields_clear_context_subject(db_path):
    task = create_unscheduled_task(db_path, "Do something", context_subject="Job Applications")
    result = patch_task_fields(db_path, task["id"], {"context_subject": None})
    assert result is not None
    assert result["context_subject"] is None


def test_patch_task_fields_context_subject_persists(db_path):
    """Setting an unrelated field should not clobber context_subject."""
    task = create_unscheduled_task(db_path, "Do something", context_subject="Tether")
    patch_task_fields(db_path, task["id"], {"status": "done"})
    updated = get_task_by_uuid(db_path, task["id"])
    assert updated["context_subject"] == "Tether"
    assert updated["status"] == "done"


# ---------------------------------------------------------------------------
# get_task_by_uuid: includes context_subject
# ---------------------------------------------------------------------------

def test_get_task_by_uuid_includes_context_subject(db_path):
    task = create_unscheduled_task(db_path, "Some task", context_subject="5D Multiverse")
    fetched = get_task_by_uuid(db_path, task["id"])
    assert fetched is not None
    assert fetched["context_subject"] == "5D Multiverse"


def test_get_task_by_uuid_context_subject_none_when_not_set(db_path):
    task = create_unscheduled_task(db_path, "No context task")
    fetched = get_task_by_uuid(db_path, task["id"])
    assert fetched["context_subject"] is None


def test_rename_context_cascades_to_tasks(db_path):
    from db.queries import create_unscheduled_task, get_task_by_uuid, rename_context_subject
    upsert_context_entry(db_path, "OldProj", "body")
    upsert_context_entry(db_path, "OldProj/Sub", "child body")
    task1 = create_unscheduled_task(db_path, "top-level task", context_subject="OldProj")
    task2 = create_unscheduled_task(db_path, "child task", context_subject="OldProj/Sub")
    rename_context_subject(db_path, "OldProj", "NewProj")
    t1 = get_task_by_uuid(db_path, task1["id"])
    t2 = get_task_by_uuid(db_path, task2["id"])
    assert t1["context_subject"] == "NewProj"
    assert t2["context_subject"] == "NewProj/Sub"


def test_get_context_tasks_returns_linked_tasks(db_path):
    from db.queries import create_unscheduled_task, get_context_tasks
    upsert_context_entry(db_path, "TestProj", "body")
    create_unscheduled_task(db_path, "linked task", context_subject="TestProj")
    create_unscheduled_task(db_path, "other task", context_subject="OtherProj")
    create_unscheduled_task(db_path, "no context task")
    tasks = get_context_tasks(db_path, "TestProj")
    assert len(tasks) == 1
    assert tasks[0]["text"] == "linked task"
    assert tasks[0]["id"] is not None
    # Should not return tasks from other contexts
    assert all(t["text"] != "other task" for t in tasks)
