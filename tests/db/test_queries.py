import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import (
    upsert_anchor, get_anchors,
    upsert_plan, get_plan,
    upsert_tasks,
    upsert_context_entry, get_context_entries, delete_context_entry,
    rename_context_subject,
    ensure_node_path, get_all_node_paths, get_node_by_path, create_node,
    insert_conversation_turn, get_recent_history,
    clear_session_state,
    insert_orchestrator_turn, get_orchestrator_conversation,
    upsert_staging_mutation, get_staging_mutations,
    log_stage, get_invocation_log,
    create_milestone, get_milestones, patch_milestone, delete_milestone,
    link_milestone_task, unlink_milestone_task,
    add_dependency, remove_dependency, get_dependencies_for,
    get_full_task_dependencies,
    get_subtasks, create_subtask, update_subtask, delete_subtask, reorder_subtasks,
    get_links, create_link, delete_link,
    patch_task_fields,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


def test_init_creates_tables(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"anchors", "plans", "tasks", "acknowledgements", "context_entries",
            "edit_history", "conversation_history"} <= tables


def test_upsert_and_get_anchor(db_path):
    upsert_anchor(db_path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                             "duration_minutes": 120, "flexibility": "locked",
                             "strictness": 4, "color": "#e05c5c", "position": 1})
    anchors = get_anchors(db_path)
    assert any(a["id"] == "grind_am" for a in anchors)
    assert anchors[0]["name"] == "The Grind"


def test_upsert_and_get_plan(db_path):
    upsert_plan(db_path, "2026-03-26")
    plan = get_plan(db_path, "2026-03-26")
    assert plan["date"] == "2026-03-26"
    assert plan["anchors"] == {}


def test_upsert_tasks_replaces_anchor_tasks(db_path):
    upsert_anchor(db_path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                             "duration_minutes": 120, "flexibility": "locked",
                             "strictness": 4, "color": "#e05c5c", "position": 1})
    upsert_plan(db_path, "2026-03-26")
    upsert_tasks(db_path, "2026-03-26", "grind_am",
                 tasks=["Apply to 3 jobs", "Follow up Stripe"], notes="ML roles")
    plan = get_plan(db_path, "2026-03-26")
    texts = [t["text"] for t in plan["anchors"]["grind_am"]["tasks"]]
    assert texts == ["Apply to 3 jobs", "Follow up Stripe"]
    assert plan["anchors"]["grind_am"]["notes"] == "ML roles"


def test_upsert_tasks_adds_without_deleting(db_path):
    """upsert_tasks no longer deletes implicitly — adding new tasks preserves existing."""
    upsert_anchor(db_path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                             "duration_minutes": 120, "flexibility": "locked",
                             "strictness": 4, "color": "#e05c5c", "position": 1})
    upsert_plan(db_path, "2026-03-26")
    upsert_tasks(db_path, "2026-03-26", "grind_am", tasks=["Old task"], notes="")
    upsert_tasks(db_path, "2026-03-26", "grind_am", tasks=["New task"], notes="")
    plan = get_plan(db_path, "2026-03-26")
    texts = [t["text"] for t in plan["anchors"]["grind_am"]["tasks"]]
    assert "Old task" in texts
    assert "New task" in texts


def test_context_entry_crud(db_path):
    upsert_context_entry(db_path, "Job Applications",
                         "Applying for ML engineer roles. Priority 1.")
    entries = get_context_entries(db_path)
    assert any(e["subject"] == "Job Applications" for e in entries)

    upsert_context_entry(db_path, "Job Applications", "Updated body.")
    entries = get_context_entries(db_path)
    match = next(e for e in entries if e["subject"] == "Job Applications")
    assert match["body"] == "Updated body."

    delete_context_entry(db_path, "Job Applications")
    entries = get_context_entries(db_path)
    assert not any(e["subject"] == "Job Applications" for e in entries)


@pytest.fixture
def hierarchical_db(db_path):
    upsert_context_entry(db_path, "Intellipat", "Top level.")
    upsert_context_entry(db_path, "Intellipat/Backend", "Backend sub.")
    upsert_context_entry(db_path, "Intellipat/Frontend", "Frontend sub.")
    upsert_context_entry(db_path, "General", "General context.")
    return db_path


def test_get_context_entries_top_level_only(hierarchical_db):
    entries = get_context_entries(hierarchical_db, top_level_only=True)
    subjects = {e["subject"] for e in entries}
    assert subjects == {"Intellipat", "General"}


def test_get_context_entries_prefix(hierarchical_db):
    entries = get_context_entries(hierarchical_db, prefix="Intellipat")
    subjects = {e["subject"] for e in entries}
    assert subjects == {"Intellipat", "Intellipat/Backend", "Intellipat/Frontend"}


def test_get_context_entries_prefix_no_cross_match(hierarchical_db):
    entries = get_context_entries(hierarchical_db, prefix="General")
    subjects = {e["subject"] for e in entries}
    assert subjects == {"General"}


def test_delete_context_entry_cascades(hierarchical_db):
    delete_context_entry(hierarchical_db, "Intellipat")
    entries = get_context_entries(hierarchical_db)
    subjects = {e["subject"] for e in entries}
    assert "Intellipat" not in subjects
    assert "Intellipat/Backend" not in subjects
    assert "Intellipat/Frontend" not in subjects
    assert "General" in subjects


def test_rename_context_subject_cascades(hierarchical_db):
    rename_context_subject(hierarchical_db, "Intellipat", "IntelliPat")
    entries = get_context_entries(hierarchical_db)
    subjects = {e["subject"] for e in entries}
    assert "Intellipat" not in subjects
    assert "Intellipat/Backend" not in subjects
    assert {"IntelliPat", "IntelliPat/Backend", "IntelliPat/Frontend", "General"} == subjects


def test_rename_context_subject_no_children(hierarchical_db):
    rename_context_subject(hierarchical_db, "General", "Overview")
    entries = get_context_entries(hierarchical_db)
    subjects = {e["subject"] for e in entries}
    assert "General" not in subjects
    assert "Overview" in subjects


# ---------------------------------------------------------------------------
# conversation_history
# ---------------------------------------------------------------------------

def test_insert_and_get_recent_history(db_path):
    insert_conversation_turn(db_path, "user", "Hello there")
    insert_conversation_turn(db_path, "assistant", "Hi! How can I help?")
    history = get_recent_history(db_path)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["body"] == "Hello there"
    assert history[1]["role"] == "assistant"
    assert history[1]["body"] == "Hi! How can I help?"


def test_get_recent_history_empty(db_path):
    assert get_recent_history(db_path) == []


def test_get_recent_history_respects_n(db_path):
    for i in range(8):
        insert_conversation_turn(db_path, "user", f"msg {i}")
        insert_conversation_turn(db_path, "assistant", f"reply {i}")
    history = get_recent_history(db_path, n=3)
    assert len(history) == 6  # 3 exchanges = 6 rows
    # Should be the most recent 3 exchanges in chronological order
    assert history[-1]["body"] == "reply 7"
    assert history[-2]["body"] == "msg 7"


def test_get_recent_history_chronological_order(db_path):
    insert_conversation_turn(db_path, "user", "first")
    insert_conversation_turn(db_path, "assistant", "second")
    insert_conversation_turn(db_path, "user", "third")
    history = get_recent_history(db_path)
    assert [r["body"] for r in history] == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# orchestrator_conversation + staging_mutations
# ---------------------------------------------------------------------------

def test_insert_and_get_orchestrator_conversation(db_path):
    insert_orchestrator_turn(db_path, "sess1", "orchestrator", "I think we should update the plan", 0)
    insert_orchestrator_turn(db_path, "sess1", "meta_eval", "Fetching Intellipat context", 0)
    conv = get_orchestrator_conversation(db_path, "sess1")
    assert len(conv) == 2
    assert conv[0]["role"] == "orchestrator"
    assert conv[0]["body"] == "I think we should update the plan"
    assert conv[0]["round_num"] == 0
    assert conv[1]["role"] == "meta_eval"


def test_get_orchestrator_conversation_empty(db_path):
    assert get_orchestrator_conversation(db_path, "nonexistent") == []


def test_orchestrator_conversation_isolated_by_session(db_path):
    insert_orchestrator_turn(db_path, "sess1", "orchestrator", "session 1 turn", 0)
    insert_orchestrator_turn(db_path, "sess2", "orchestrator", "session 2 turn", 0)
    assert len(get_orchestrator_conversation(db_path, "sess1")) == 1
    assert len(get_orchestrator_conversation(db_path, "sess2")) == 1


def test_upsert_and_get_staging_mutations(db_path):
    upsert_staging_mutation(db_path, "sess1", "mut1", "update_plan",
                            "Set grind_am tasks for today", '{"anchor_id": "grind_am"}')
    upsert_staging_mutation(db_path, "sess1", "mut2", "chat",
                            "Answer question about schedule", '{"message": "hi"}')
    mutations = get_staging_mutations(db_path, "sess1")
    assert len(mutations) == 2
    assert mutations[0]["id"] == "mut1"
    assert mutations[0]["type"] == "update_plan"
    assert mutations[1]["id"] == "mut2"


def test_upsert_staging_mutation_updates_existing(db_path):
    upsert_staging_mutation(db_path, "sess1", "mut1", "update_plan", "original desc", "{}")
    upsert_staging_mutation(db_path, "sess1", "mut1", "update_plan", "updated desc", '{"key": "val"}')
    mutations = get_staging_mutations(db_path, "sess1")
    assert len(mutations) == 1
    assert mutations[0]["description"] == "updated desc"
    assert mutations[0]["params_json"] == '{"key": "val"}'


def test_get_staging_mutations_empty(db_path):
    assert get_staging_mutations(db_path, "nonexistent") == []


def test_staging_mutations_isolated_by_session(db_path):
    upsert_staging_mutation(db_path, "sess1", "mut1", "update_plan", "sess1 mut", "{}")
    upsert_staging_mutation(db_path, "sess2", "mut2", "chat", "sess2 mut", "{}")
    assert len(get_staging_mutations(db_path, "sess1")) == 1
    assert len(get_staging_mutations(db_path, "sess2")) == 1


def test_clear_session_state(db_path):
    insert_orchestrator_turn(db_path, "sess1", "orchestrator", "some turn", 0)
    upsert_staging_mutation(db_path, "sess1", "mut1", "update_plan", "a mutation", "{}")
    # add another session that should not be cleared
    insert_orchestrator_turn(db_path, "sess2", "orchestrator", "other session", 0)
    clear_session_state(db_path, "sess1")
    assert get_orchestrator_conversation(db_path, "sess1") == []
    assert get_staging_mutations(db_path, "sess1") == []
    # sess2 untouched
    assert len(get_orchestrator_conversation(db_path, "sess2")) == 1


def test_init_creates_new_tables(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "staging_mutations" in tables
    assert "orchestrator_conversation" in tables
    assert "invocation_log" in tables


# ---------------------------------------------------------------------------
# invocation_log
# ---------------------------------------------------------------------------

def test_log_stage_inserts_entry(db_path):
    log_stage(db_path, "sess1", "orchestrator_0", "the prompt", "the response")
    entries = get_invocation_log(db_path, n=1)
    assert len(entries) == 1
    assert entries[0]["session_id"] == "sess1"
    assert entries[0]["stage"] == "orchestrator_0"
    assert entries[0]["prompt"] == "the prompt"
    assert entries[0]["response"] == "the response"
    assert entries[0]["error"] is None


def test_log_stage_records_error(db_path):
    log_stage(db_path, "sess1", "meta_eval_0", "prompt", "", error="timeout after 45s")
    entries = get_invocation_log(db_path, n=1)
    assert entries[0]["error"] == "timeout after 45s"


def test_get_invocation_log_returns_n_sessions(db_path):
    for i in range(4):
        log_stage(db_path, f"sess{i}", f"stage_{i}", "p", "r")
    # n=2 should return only the last 2 sessions
    entries = get_invocation_log(db_path, n=2)
    session_ids = {e["session_id"] for e in entries}
    assert session_ids == {"sess2", "sess3"}


def test_log_stage_prunes_beyond_10_sessions(db_path):
    for i in range(12):
        log_stage(db_path, f"sess{i}", "stage", "p", "r")
    entries = get_invocation_log(db_path, n=99)
    session_ids = {e["session_id"] for e in entries}
    # Only the 10 most recent sessions survive
    assert len(session_ids) == 10
    assert "sess0" not in session_ids
    assert "sess1" not in session_ids
    assert "sess11" in session_ids


def test_get_invocation_log_multiple_stages_per_session(db_path):
    for stage in ["orchestrator_0", "meta_eval_0", "subagent_update_plan", "response_builder"]:
        log_stage(db_path, "sess1", stage, "prompt", "response")
    entries = get_invocation_log(db_path, n=1)
    stages = [e["stage"] for e in entries]
    assert stages == ["orchestrator_0", "meta_eval_0", "subagent_update_plan", "response_builder"]


# ---------------------------------------------------------------------------
# Task model v2: upsert_tasks returns list[dict] with UUIDs
# ---------------------------------------------------------------------------

_ANCHOR = {"id": "grind_am", "name": "The Grind", "time": "08:00",
           "duration_minutes": 120, "flexibility": "locked",
           "strictness": 4, "color": "#e05c5c", "position": 1}


def test_upsert_tasks_returns_uuid_for_new_task(db_path):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am",
                         [{"text": "Apply to Adobe", "status": "pending"}], notes="")
    assert len(tasks) == 1
    assert tasks[0]["id"] is not None
    assert len(tasks[0]["id"]) == 36
    assert tasks[0]["text"] == "Apply to Adobe"
    assert tasks[0]["status"] == "pending"


def test_upsert_tasks_preserves_uuid_on_update(db_path):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am",
                         [{"text": "Apply", "status": "pending"}], notes="")
    uid = tasks[0]["id"]
    updated = upsert_tasks(db_path, "2026-03-30", "grind_am",
                           [{"id": uid, "text": "Apply v2", "status": "in_progress"}], notes="")
    assert updated[0]["id"] == uid
    assert updated[0]["text"] == "Apply v2"
    assert updated[0]["status"] == "in_progress"


def test_upsert_tasks_does_not_delete_on_omit(db_path):
    """upsert_tasks never deletes implicitly — use delete_task_by_uuid for that."""
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am",
                         [{"text": "Task A"}, {"text": "Task B"}], notes="")
    uid_a = tasks[0]["id"]
    # Update just Task A — Task B should still exist
    updated = upsert_tasks(db_path, "2026-03-30", "grind_am",
                           [{"id": uid_a, "text": "Task A updated"}], notes="")
    assert len(updated) == 2  # Both tasks still present
    texts = [t["text"] for t in updated]
    assert "Task A updated" in texts
    assert "Task B" in texts


def test_explicit_delete_removes_task(db_path):
    """delete_task_by_uuid is the only way to remove a task."""
    from db.queries import delete_task_by_uuid
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am",
                         [{"text": "Keep"}, {"text": "Remove"}], notes="")
    delete_task_by_uuid(db_path, tasks[1]["id"])
    plan = get_plan(db_path, "2026-03-30")
    texts = [t["text"] for t in plan["anchors"]["grind_am"]["tasks"]]
    assert texts == ["Keep"]


# ---------------------------------------------------------------------------
# Task model v2: get_plan returns task objects
# ---------------------------------------------------------------------------

def test_get_plan_returns_task_objects(db_path):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    upsert_tasks(db_path, "2026-03-30", "grind_am",
                 [{"text": "Apply", "status": "in_progress"}], notes="")
    plan = get_plan(db_path, "2026-03-30")
    task = plan["anchors"]["grind_am"]["tasks"][0]
    assert isinstance(task, dict)
    assert task["text"] == "Apply"
    assert task["status"] == "in_progress"
    assert task["id"] is not None and len(task["id"]) == 36
    assert task["blocks"] == []
    assert task["blocked_by"] == []


# ---------------------------------------------------------------------------
# Task model v2: patch_task_fields, move_task_atomic, dependencies
# ---------------------------------------------------------------------------

def test_patch_task_fields_updates_status(db_path):
    from db.queries import patch_task_fields
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "Task"}], notes="")
    uid = tasks[0]["id"]
    result = patch_task_fields(db_path, uid, {"status": "done"})
    assert result["status"] == "done"
    assert result["id"] == uid


def test_patch_task_fields_returns_none_for_missing(db_path):
    from db.queries import patch_task_fields
    assert patch_task_fields(db_path, "nonexistent-uuid", {"status": "done"}) is None


def test_move_task_atomic(db_path):
    from db.queries import move_task_atomic
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    upsert_plan(db_path, "2026-03-31")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "Move me"}], notes="")
    uid = tasks[0]["id"]
    move_task_atomic(db_path, uid, "2026-03-31", "grind_am", position=0)
    src = get_plan(db_path, "2026-03-30")
    dst = get_plan(db_path, "2026-03-31")
    assert src["anchors"].get("grind_am", {}).get("tasks", []) == []
    assert dst["anchors"]["grind_am"]["tasks"][0]["text"] == "Move me"
    assert dst["anchors"]["grind_am"]["tasks"][0]["id"] == uid


def test_add_and_remove_task_dependency(db_path):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am",
                         [{"text": "Task A"}, {"text": "Task B"}], notes="")
    uid_a, uid_b = tasks[0]["id"], tasks[1]["id"]
    # A blocks B (A is blocker, B is blocked)
    dep_id = add_dependency(db_path, "task", uid_a, "task", uid_b)
    plan = get_plan(db_path, "2026-03-30")
    task_b = next(t for t in plan["anchors"]["grind_am"]["tasks"] if t["id"] == uid_b)
    assert uid_a in task_b["blocked_by"]
    remove_dependency(db_path, dep_id)
    plan2 = get_plan(db_path, "2026-03-30")
    task_b2 = next(t for t in plan2["anchors"]["grind_am"]["tasks"] if t["id"] == uid_b)
    assert task_b2["blocked_by"] == []


# ── Milestone tests ──────────────────────────────────────────────────────────

def test_create_milestone_returns_dict_with_uuid(db_path):
    upsert_context_entry(db_path, "Proj", "body")
    m = create_milestone(db_path, "Proj", "Backend API")
    assert len(m["id"]) == 36
    assert m["name"] == "Backend API"
    assert m["status"] == "pending"
    assert m["status_override"] is False
    assert m["task_count"] == 0
    assert m["done_count"] == 0


def test_get_milestones_returns_list_for_subject(db_path):
    upsert_context_entry(db_path, "Proj", "body")
    create_milestone(db_path, "Proj", "M1")
    create_milestone(db_path, "Proj", "M2")
    ms = get_milestones(db_path, "Proj")
    assert len(ms) == 2
    assert ms[0]["name"] == "M1"


def test_get_milestones_no_subject_returns_all(db_path):
    upsert_context_entry(db_path, "A", "body")
    upsert_context_entry(db_path, "B", "body")
    create_milestone(db_path, "A", "MA")
    create_milestone(db_path, "B", "MB")
    assert len(get_milestones(db_path)) == 2


def test_derive_milestone_status_in_progress(db_path):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    upsert_context_entry(db_path, "Proj", "body")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am",
                         [{"text": "T1", "status": "done"}, {"text": "T2", "status": "pending"}],
                         notes="")
    m = create_milestone(db_path, "Proj", "Goal")
    link_milestone_task(db_path, m["id"], tasks[0]["id"])
    link_milestone_task(db_path, m["id"], tasks[1]["id"])
    ms = get_milestones(db_path, "Proj")
    assert ms[0]["status"] == "in_progress"
    assert ms[0]["task_count"] == 2
    assert ms[0]["done_count"] == 1


def test_derive_milestone_status_all_done(db_path):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    upsert_context_entry(db_path, "Proj", "body")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am",
                         [{"text": "T1", "status": "done"}], notes="")
    m = create_milestone(db_path, "Proj", "Goal")
    link_milestone_task(db_path, m["id"], tasks[0]["id"])
    assert get_milestones(db_path, "Proj")[0]["status"] == "done"


def test_derive_milestone_status_blocked(db_path):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    upsert_context_entry(db_path, "Proj", "body")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am",
                         [{"text": "T1", "status": "blocked"}, {"text": "T2", "status": "pending"}],
                         notes="")
    m = create_milestone(db_path, "Proj", "Goal")
    link_milestone_task(db_path, m["id"], tasks[0]["id"])
    link_milestone_task(db_path, m["id"], tasks[1]["id"])
    assert get_milestones(db_path, "Proj")[0]["status"] == "blocked"


def test_patch_milestone_name(db_path):
    upsert_context_entry(db_path, "Proj", "body")
    m = create_milestone(db_path, "Proj", "Old")
    updated = patch_milestone(db_path, m["id"], {"name": "New"})
    assert updated["name"] == "New"


def test_patch_milestone_status_sets_override(db_path):
    upsert_context_entry(db_path, "Proj", "body")
    m = create_milestone(db_path, "Proj", "Goal")
    updated = patch_milestone(db_path, m["id"], {"status": "done"})
    assert updated["status"] == "done"
    assert updated["status_override"] is True


def test_patch_milestone_returns_none_for_missing(db_path):
    assert patch_milestone(db_path, "nonexistent", {"name": "x"}) is None


def test_delete_milestone(db_path):
    upsert_context_entry(db_path, "Proj", "body")
    m = create_milestone(db_path, "Proj", "Temp")
    delete_milestone(db_path, m["id"])
    assert get_milestones(db_path, "Proj") == []


def test_link_and_unlink_milestone_task(db_path):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    upsert_context_entry(db_path, "Proj", "body")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "T1"}], notes="")
    m = create_milestone(db_path, "Proj", "Goal")
    link_milestone_task(db_path, m["id"], tasks[0]["id"])
    assert tasks[0]["id"] in get_milestones(db_path, "Proj")[0]["task_ids"]
    unlink_milestone_task(db_path, m["id"], tasks[0]["id"])
    assert get_milestones(db_path, "Proj")[0]["task_ids"] == []


def test_rename_context_cascades_to_milestones(db_path):
    upsert_context_entry(db_path, "OldProj", "body")
    create_milestone(db_path, "OldProj", "Goal")
    rename_context_subject(db_path, "OldProj", "NewProj")
    assert get_milestones(db_path, "OldProj") == []
    assert len(get_milestones(db_path, "NewProj")) == 1


# ── Follow-up state tests ────────────────────────────────────────────────────

ANCHOR = {"id": "grind_am", "name": "The Grind", "time": "08:00",
          "duration_minutes": 120, "flexibility": "locked",
          "strictness": 4, "color": "#e05c5c", "position": 1}


def test_init_followup_state_creates_row(db_path):
    from db.queries import init_followup_state, get_active_followup_states, upsert_plan
    from datetime import datetime
    upsert_anchor(db_path, ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "T1"}], notes="")
    now = datetime(2026, 3, 30, 8, 0, 0)
    init_followup_state(db_path, "2026-03-30", "grind_am", tasks[0]["id"], now)
    rows = get_active_followup_states(db_path, "2026-03-30")
    assert len(rows) == 1
    assert rows[0]["task_id"] == tasks[0]["id"]
    assert rows[0]["pre_ack_pings_sent"] == 0
    assert rows[0]["acknowledged_at"] is None


def test_init_followup_state_is_idempotent(db_path):
    from db.queries import init_followup_state, get_active_followup_states, upsert_plan
    from datetime import datetime
    upsert_anchor(db_path, ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "T1"}], notes="")
    now = datetime(2026, 3, 30, 8, 0, 0)
    init_followup_state(db_path, "2026-03-30", "grind_am", tasks[0]["id"], now)
    init_followup_state(db_path, "2026-03-30", "grind_am", tasks[0]["id"], now)
    rows = get_active_followup_states(db_path, "2026-03-30")
    assert len(rows) == 1


def test_acknowledge_followup_sets_acknowledged_at(db_path):
    from db.queries import init_followup_state, acknowledge_followup, get_active_followup_states, upsert_plan
    from datetime import datetime
    upsert_anchor(db_path, ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "T1"}], notes="")
    now = datetime(2026, 3, 30, 8, 0, 0)
    init_followup_state(db_path, "2026-03-30", "grind_am", tasks[0]["id"], now)
    ack_time = datetime(2026, 3, 30, 8, 7, 0)
    acknowledge_followup(db_path, "2026-03-30", "grind_am", ack_time)
    rows = get_active_followup_states(db_path, "2026-03-30")
    assert rows[0]["acknowledged_at"] is not None


def test_record_pings_increments_count(db_path):
    from db.queries import init_followup_state, record_ping, get_active_followup_states, upsert_plan
    from datetime import datetime
    upsert_anchor(db_path, ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "T1"}], notes="")
    now = datetime(2026, 3, 30, 8, 0, 0)
    init_followup_state(db_path, "2026-03-30", "grind_am", tasks[0]["id"], now)
    rows = get_active_followup_states(db_path, "2026-03-30")
    ping_time = datetime(2026, 3, 30, 8, 5, 0)
    record_ping(db_path, rows[0]["id"], "pre", ping_time)
    rows2 = get_active_followup_states(db_path, "2026-03-30")
    assert rows2[0]["pre_ack_pings_sent"] == 1
    assert rows2[0]["last_ping_at"] is not None


def test_get_active_followup_states_excludes_completed(db_path):
    from db.queries import init_followup_state, mark_followup_completed, get_active_followup_states, upsert_plan
    from datetime import datetime
    upsert_anchor(db_path, ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "T1"}], notes="")
    now = datetime(2026, 3, 30, 8, 0, 0)
    init_followup_state(db_path, "2026-03-30", "grind_am", tasks[0]["id"], now)
    mark_followup_completed(db_path, tasks[0]["id"], "2026-03-30")
    rows = get_active_followup_states(db_path, "2026-03-30")
    assert rows == []


def test_resolve_followup_config_returns_anchor_config_when_no_task_override(db_path):
    from db.queries import resolve_followup_config, upsert_plan
    fc = {"enabled": True, "pre_ack_interval_min": 5, "pre_ack_max_pings": 3,
          "post_ack_interval_min": 15, "post_ack_pings": 2}
    upsert_anchor(db_path, {**ANCHOR, "followup_config": fc})
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "T1"}], notes="")
    result = resolve_followup_config(db_path, "grind_am", tasks[0]["id"])
    assert result is not None
    assert result["pre_ack_interval_min"] == 5


def test_resolve_followup_config_task_overrides_anchor(db_path):
    from db.queries import resolve_followup_config, upsert_plan
    anchor_fc = {"enabled": True, "pre_ack_interval_min": 5, "pre_ack_max_pings": 3,
                 "post_ack_interval_min": 15, "post_ack_pings": 2}
    task_fc = {"enabled": True, "pre_ack_interval_min": 2, "pre_ack_max_pings": 5,
               "post_ack_interval_min": 10, "post_ack_pings": 3}
    upsert_anchor(db_path, {**ANCHOR, "followup_config": anchor_fc})
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am",
                         [{"text": "T1", "followup_config": task_fc}], notes="")
    result = resolve_followup_config(db_path, "grind_am", tasks[0]["id"])
    assert result is not None
    assert result["pre_ack_interval_min"] == 2  # task's value, not anchor's


def test_resolve_followup_config_returns_none_when_disabled(db_path):
    from db.queries import resolve_followup_config, upsert_plan
    fc = {"enabled": False, "pre_ack_interval_min": 5, "pre_ack_max_pings": 3,
          "post_ack_interval_min": 15, "post_ack_pings": 2}
    upsert_anchor(db_path, {**ANCHOR, "followup_config": fc})
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "T1"}], notes="")
    result = resolve_followup_config(db_path, "grind_am", tasks[0]["id"])
    assert result is None


def test_resolve_followup_config_returns_none_when_no_config(db_path):
    from db.queries import resolve_followup_config, upsert_plan
    upsert_anchor(db_path, ANCHOR)  # no followup_config
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "T1"}], notes="")
    result = resolve_followup_config(db_path, "grind_am", tasks[0]["id"])
    assert result is None


# ---------------------------------------------------------------------------
# Dependencies (new table)
# ---------------------------------------------------------------------------

def _make_tasks(db_path, count=2, date="2026-03-30"):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, date)
    return upsert_tasks(db_path, date, "grind_am",
                        [{"text": f"Task {i}"} for i in range(count)], notes="")


def test_add_and_get_dependency(db_path):
    tasks = _make_tasks(db_path, 2)
    uid_a, uid_b = tasks[0]["id"], tasks[1]["id"]
    dep_id = add_dependency(db_path, "task", uid_a, "task", uid_b)
    assert isinstance(dep_id, int) and dep_id > 0

    deps_a = get_dependencies_for(db_path, "task", uid_a)
    assert len(deps_a["blocks"]) == 1
    assert deps_a["blocks"][0]["entity_id"] == uid_b
    assert deps_a["blocks"][0]["type"] == "task"
    assert deps_a["blocked_by"] == []

    deps_b = get_dependencies_for(db_path, "task", uid_b)
    assert len(deps_b["blocked_by"]) == 1
    assert deps_b["blocked_by"][0]["entity_id"] == uid_a
    assert deps_b["blocked_by"][0]["type"] == "task"
    assert deps_b["blocks"] == []


def test_add_task_milestone_dependency(db_path):
    tasks = _make_tasks(db_path, 1)
    uid = tasks[0]["id"]
    upsert_context_entry(db_path, "Proj", "body")
    m = create_milestone(db_path, "Proj", "M1")
    dep_id = add_dependency(db_path, "task", uid, "milestone", m["id"])
    assert isinstance(dep_id, int) and dep_id > 0

    deps = get_dependencies_for(db_path, "task", uid)
    assert len(deps["blocks"]) == 1
    assert deps["blocks"][0]["type"] == "milestone"
    assert deps["blocks"][0]["entity_id"] == m["id"]


def test_remove_dependency(db_path):
    tasks = _make_tasks(db_path, 2)
    uid_a, uid_b = tasks[0]["id"], tasks[1]["id"]
    dep_id = add_dependency(db_path, "task", uid_a, "task", uid_b)
    remove_dependency(db_path, dep_id)
    deps = get_dependencies_for(db_path, "task", uid_a)
    assert deps["blocks"] == []
    assert deps["blocked_by"] == []


def test_get_plan_uses_dependencies_table(db_path):
    tasks = _make_tasks(db_path, 2)
    uid_a, uid_b = tasks[0]["id"], tasks[1]["id"]
    # Use new dependencies table (not task_dependencies)
    add_dependency(db_path, "task", uid_a, "task", uid_b)
    plan = get_plan(db_path, "2026-03-30")
    plan_tasks = plan["anchors"]["grind_am"]["tasks"]
    task_a = next(t for t in plan_tasks if t["id"] == uid_a)
    task_b = next(t for t in plan_tasks if t["id"] == uid_b)
    assert uid_b in task_a["blocks"]
    assert uid_a in task_b["blocked_by"]


# ---------------------------------------------------------------------------
# Subtasks
# ---------------------------------------------------------------------------

def test_create_and_get_subtasks(db_path):
    tasks = _make_tasks(db_path, 1)
    tid = tasks[0]["id"]
    s1 = create_subtask(db_path, tid, "Step one", 0)
    s2 = create_subtask(db_path, tid, "Step two", 1)
    assert s1["text"] == "Step one"
    assert s2["text"] == "Step two"
    subtasks = get_subtasks(db_path, tid)
    assert len(subtasks) == 2
    assert subtasks[0]["position"] == 0
    assert subtasks[1]["position"] == 1
    assert subtasks[0]["text"] == "Step one"


def test_update_subtask_done(db_path):
    tasks = _make_tasks(db_path, 1)
    tid = tasks[0]["id"]
    s = create_subtask(db_path, tid, "Do thing", 0)
    assert s["done"] == 0
    update_subtask(db_path, s["id"], done=1)
    subtasks = get_subtasks(db_path, tid)
    assert subtasks[0]["done"] == 1


def test_delete_subtask(db_path):
    tasks = _make_tasks(db_path, 1)
    tid = tasks[0]["id"]
    s = create_subtask(db_path, tid, "Temp step", 0)
    delete_subtask(db_path, s["id"])
    assert get_subtasks(db_path, tid) == []


def test_reorder_subtasks(db_path):
    tasks = _make_tasks(db_path, 1)
    tid = tasks[0]["id"]
    s1 = create_subtask(db_path, tid, "First", 0)
    s2 = create_subtask(db_path, tid, "Second", 1)
    s3 = create_subtask(db_path, tid, "Third", 2)
    # Reverse the order
    reorder_subtasks(db_path, tid, [s3["id"], s2["id"], s1["id"]])
    subtasks = get_subtasks(db_path, tid)
    assert subtasks[0]["id"] == s3["id"]
    assert subtasks[1]["id"] == s2["id"]
    assert subtasks[2]["id"] == s1["id"]


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def test_create_and_get_links(db_path):
    tasks = _make_tasks(db_path, 1)
    tid = tasks[0]["id"]
    link = create_link(db_path, "task", tid, "https://example.com", "Example", "reference")
    assert link["url"] == "https://example.com"
    assert link["label"] == "Example"
    assert link["category"] == "reference"
    assert link["parent_type"] == "task"
    assert link["parent_id"] == tid

    links = get_links(db_path, "task", tid)
    assert len(links) == 1
    assert links[0]["url"] == "https://example.com"


def test_delete_link(db_path):
    tasks = _make_tasks(db_path, 1)
    tid = tasks[0]["id"]
    link = create_link(db_path, "task", tid, "https://example.com", None, "other")
    delete_link(db_path, link["id"])
    assert get_links(db_path, "task", tid) == []


def test_links_for_milestone(db_path):
    upsert_context_entry(db_path, "Proj", "body")
    m = create_milestone(db_path, "Proj", "M1")
    link = create_link(db_path, "milestone", m["id"], "https://docs.example.com", "Docs", "docs")
    links = get_links(db_path, "milestone", m["id"])
    assert len(links) == 1
    assert links[0]["parent_type"] == "milestone"
    assert links[0]["label"] == "Docs"


# ---------------------------------------------------------------------------
# patch_task description
# ---------------------------------------------------------------------------

def test_patch_task_description(db_path):
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    tasks = upsert_tasks(db_path, "2026-03-30", "grind_am", [{"text": "Task"}], notes="")
    uid = tasks[0]["id"]
    result = patch_task_fields(db_path, uid, {"description": "A detailed description."})
    assert result is not None
    assert result["description"] == "A detailed description."

    plan = get_plan(db_path, "2026-03-30")
    task = plan["anchors"]["grind_am"]["tasks"][0]
    assert task["description"] == "A detailed description."


# ---------------------------------------------------------------------------
# get_full_task_dependencies — cross-day dependency resolution
# ---------------------------------------------------------------------------

def test_milestone_color_roundtrip(db_path):
    upsert_context_entry(db_path, "Proj", "body")
    m = create_milestone(db_path, "Proj", "Ship v2", color="#ff6b6b")
    assert m["color"] == "#ff6b6b"
    ms = get_milestones(db_path, "Proj")
    assert ms[0]["color"] == "#ff6b6b"
    patch_milestone(db_path, m["id"], {"color": "#4ecdc4"})
    ms2 = get_milestones(db_path, "Proj")
    assert ms2[0]["color"] == "#4ecdc4"


# ---------------------------------------------------------------------------
# get_full_task_dependencies — cross-day dependency resolution
# ---------------------------------------------------------------------------

def test_get_full_task_dependencies_cross_day(db_path):
    # Create tasks on two different dates
    upsert_anchor(db_path, _ANCHOR)
    upsert_plan(db_path, "2026-03-30")
    upsert_plan(db_path, "2026-03-31")
    tasks_day1 = upsert_tasks(db_path, "2026-03-30", "grind_am",
                               [{"text": "Day1 Task"}], notes="")
    tasks_day2 = upsert_tasks(db_path, "2026-03-31", "grind_am",
                               [{"text": "Day2 Task"}], notes="")
    uid_day1 = tasks_day1[0]["id"]
    uid_day2 = tasks_day2[0]["id"]

    # Day1 task blocks Day2 task (cross-day dependency)
    add_dependency(db_path, "task", uid_day1, "task", uid_day2)

    deps_day1 = get_full_task_dependencies(db_path, uid_day1)
    assert len(deps_day1["blocks"]) == 1
    assert deps_day1["blocks"][0]["type"] == "task"
    assert deps_day1["blocks"][0]["id"] == uid_day2
    assert deps_day1["blocked_by"] == []

    deps_day2 = get_full_task_dependencies(db_path, uid_day2)
    assert deps_day2["blocks"] == []
    assert len(deps_day2["blocked_by"]) == 1
    assert deps_day2["blocked_by"][0]["type"] == "task"
    assert deps_day2["blocked_by"][0]["id"] == uid_day1


# ---------------------------------------------------------------------------
# ensure_node_path + get_all_node_paths
# ---------------------------------------------------------------------------


def test_ensure_node_path_creates_intermediates(db_path):
    node = ensure_node_path(db_path, "School/ML/Project")
    assert node["name"] == "Project"
    # Intermediates should exist
    school = get_node_by_path(db_path, "School")
    assert school is not None
    ml = get_node_by_path(db_path, "School/ML")
    assert ml is not None
    assert ml["parent_id"] == school["id"]
    assert node["parent_id"] == ml["id"]


def test_ensure_node_path_idempotent(db_path):
    node1 = ensure_node_path(db_path, "School/ML/Project")
    node2 = ensure_node_path(db_path, "School/ML/Project")
    assert node1["id"] == node2["id"]


def test_ensure_node_path_single_segment(db_path):
    node = ensure_node_path(db_path, "Thesis")
    assert node["name"] == "Thesis"
    assert node["parent_id"] is None


def test_ensure_node_path_empty_raises(db_path):
    with pytest.raises(ValueError):
        ensure_node_path(db_path, "")


def test_ensure_node_path_reuses_existing_parents(db_path):
    create_node(db_path, None, "Existing")
    node = ensure_node_path(db_path, "Existing/Child")
    existing = get_node_by_path(db_path, "Existing")
    assert node["parent_id"] == existing["id"]


def test_get_all_node_paths_empty(db_path):
    assert get_all_node_paths(db_path) == []


def test_get_all_node_paths_tree(db_path):
    ensure_node_path(db_path, "School/ML")
    ensure_node_path(db_path, "School/Thesis")
    ensure_node_path(db_path, "Work")
    paths = get_all_node_paths(db_path)
    assert "School" in paths
    assert "School/ML" in paths
    assert "School/Thesis" in paths
    assert "Work" in paths


def test_get_all_node_paths_excludes_archived(db_path):
    from db.queries import archive_node
    node = ensure_node_path(db_path, "Old")
    archive_node(db_path, node["id"])
    paths = get_all_node_paths(db_path)
    assert "Old" not in paths
