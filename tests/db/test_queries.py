import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import (
    upsert_anchor, get_anchors,
    upsert_plan, get_plan,
    upsert_tasks,
    upsert_context_entry, get_context_entries, delete_context_entry,
    rename_context_subject,
    insert_conversation_turn, get_recent_history,
    clear_session_state,
    insert_orchestrator_turn, get_orchestrator_conversation,
    upsert_staging_mutation, get_staging_mutations,
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
    assert plan["anchors"]["grind_am"]["tasks"] == ["Apply to 3 jobs", "Follow up Stripe"]
    assert plan["anchors"]["grind_am"]["notes"] == "ML roles"


def test_upsert_tasks_replaces_existing(db_path):
    upsert_anchor(db_path, {"id": "grind_am", "name": "The Grind", "time": "08:00",
                             "duration_minutes": 120, "flexibility": "locked",
                             "strictness": 4, "color": "#e05c5c", "position": 1})
    upsert_plan(db_path, "2026-03-26")
    upsert_tasks(db_path, "2026-03-26", "grind_am", tasks=["Old task"], notes="")
    upsert_tasks(db_path, "2026-03-26", "grind_am", tasks=["New task"], notes="")
    plan = get_plan(db_path, "2026-03-26")
    assert plan["anchors"]["grind_am"]["tasks"] == ["New task"]


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
