"""Tests for context tree query functions (context_nodes, node_sections, node_tasks)."""
import sqlite3
import pytest
from pathlib import Path
from db.schema import init_db
from db import queries as q


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


def _insert_task(db_path, uuid, text, status="pending"):
    """Helper: insert a bare task directly for linking tests."""
    from db.schema import get_db
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO tasks (uuid, text, status) VALUES (?, ?, ?)",
            (uuid, text, status),
        )


# ---------------------------------------------------------------------------
# create_node
# ---------------------------------------------------------------------------

class TestCreateNode:
    def test_create_context_node(self, db_path):
        node = q.create_node(db_path, None, "School")
        assert node["name"] == "School"
        assert node["node_type"] == "context"
        assert node["parent_id"] is None
        assert node["archived"] == 0
        assert node["id"]

    def test_create_milestone_node(self, db_path):
        parent = q.create_node(db_path, None, "Project")
        ms = q.create_node(
            db_path, parent["id"], "MVP",
            node_type="milestone", target_date="2026-06-01", color="#ff0000",
        )
        assert ms["node_type"] == "milestone"
        assert ms["parent_id"] == parent["id"]
        assert ms["target_date"] == "2026-06-01"
        assert ms["color"] == "#ff0000"

    def test_create_nested_node(self, db_path):
        root = q.create_node(db_path, None, "School")
        child = q.create_node(db_path, root["id"], "ML")
        assert child["parent_id"] == root["id"]

    def test_duplicate_sibling_name_raises(self, db_path):
        q.create_node(db_path, None, "School")
        with pytest.raises(sqlite3.IntegrityError):
            q.create_node(db_path, None, "School")


# ---------------------------------------------------------------------------
# get_node
# ---------------------------------------------------------------------------

class TestGetNode:
    def test_get_existing(self, db_path):
        created = q.create_node(db_path, None, "Work")
        fetched = q.get_node(db_path, created["id"])
        assert fetched["name"] == "Work"
        assert fetched["section_types"] == []
        assert fetched["children_count"] == 0

    def test_get_with_sections_and_children(self, db_path):
        parent = q.create_node(db_path, None, "Work")
        q.create_node(db_path, parent["id"], "Sub1")
        q.create_node(db_path, parent["id"], "Sub2")
        q.upsert_section(db_path, parent["id"], "details", "some info")
        q.upsert_section(db_path, parent["id"], "notes", "extra notes")

        fetched = q.get_node(db_path, parent["id"])
        assert fetched["children_count"] == 2
        assert fetched["section_types"] == ["details", "notes"]

    def test_get_nonexistent(self, db_path):
        assert q.get_node(db_path, "nope") is None


# ---------------------------------------------------------------------------
# get_node_by_path
# ---------------------------------------------------------------------------

class TestGetNodeByPath:
    def test_single_segment(self, db_path):
        q.create_node(db_path, None, "School")
        node = q.get_node_by_path(db_path, "School")
        assert node is not None
        assert node["name"] == "School"

    def test_multi_segment(self, db_path):
        root = q.create_node(db_path, None, "School")
        mid = q.create_node(db_path, root["id"], "ML")
        leaf = q.create_node(db_path, mid["id"], "Project")
        node = q.get_node_by_path(db_path, "School/ML/Project")
        assert node is not None
        assert node["id"] == leaf["id"]

    def test_nonexistent_path(self, db_path):
        q.create_node(db_path, None, "School")
        assert q.get_node_by_path(db_path, "School/Physics") is None

    def test_nonexistent_root(self, db_path):
        assert q.get_node_by_path(db_path, "Nope") is None


# ---------------------------------------------------------------------------
# get_node_path
# ---------------------------------------------------------------------------

class TestGetNodePath:
    def test_root_node(self, db_path):
        root = q.create_node(db_path, None, "School")
        assert q.get_node_path(db_path, root["id"]) == "School"

    def test_nested_path(self, db_path):
        root = q.create_node(db_path, None, "School")
        mid = q.create_node(db_path, root["id"], "ML")
        leaf = q.create_node(db_path, mid["id"], "Project")
        assert q.get_node_path(db_path, leaf["id"]) == "School/ML/Project"


# ---------------------------------------------------------------------------
# get_children
# ---------------------------------------------------------------------------

class TestGetChildren:
    def test_root_children(self, db_path):
        q.create_node(db_path, None, "A")
        q.create_node(db_path, None, "B")
        children = q.get_children(db_path)
        assert len(children) == 2
        assert [c["name"] for c in children] == ["A", "B"]

    def test_nested_children(self, db_path):
        root = q.create_node(db_path, None, "Root")
        q.create_node(db_path, root["id"], "C1")
        q.create_node(db_path, root["id"], "C2")
        children = q.get_children(db_path, root["id"])
        assert len(children) == 2

    def test_excludes_archived_by_default(self, db_path):
        root = q.create_node(db_path, None, "Root")
        q.create_node(db_path, root["id"], "Active")
        archived = q.create_node(db_path, root["id"], "Old")
        q.archive_node(db_path, archived["id"])

        children = q.get_children(db_path, root["id"])
        assert len(children) == 1
        assert children[0]["name"] == "Active"

    def test_include_archived(self, db_path):
        root = q.create_node(db_path, None, "Root")
        q.create_node(db_path, root["id"], "Active")
        archived = q.create_node(db_path, root["id"], "Old")
        q.archive_node(db_path, archived["id"])

        children = q.get_children(db_path, root["id"], include_archived=True)
        assert len(children) == 2


# ---------------------------------------------------------------------------
# get_subtree
# ---------------------------------------------------------------------------

class TestGetSubtree:
    def test_subtree(self, db_path):
        root = q.create_node(db_path, None, "Root")
        c1 = q.create_node(db_path, root["id"], "C1")
        q.create_node(db_path, c1["id"], "GC1")
        q.create_node(db_path, root["id"], "C2")

        subtree = q.get_subtree(db_path, root["id"])
        names = {n["name"] for n in subtree}
        assert names == {"C1", "C2", "GC1"}
        # Root itself should NOT be in subtree
        assert all(n["id"] != root["id"] for n in subtree)

    def test_subtree_excludes_archived(self, db_path):
        root = q.create_node(db_path, None, "Root")
        active = q.create_node(db_path, root["id"], "Active")
        archived = q.create_node(db_path, root["id"], "Archived")
        q.archive_node(db_path, archived["id"])

        subtree = q.get_subtree(db_path, root["id"])
        names = {n["name"] for n in subtree}
        assert "Active" in names
        assert "Archived" not in names

    def test_subtree_include_archived(self, db_path):
        root = q.create_node(db_path, None, "Root")
        q.create_node(db_path, root["id"], "Active")
        archived = q.create_node(db_path, root["id"], "Archived")
        q.archive_node(db_path, archived["id"])

        subtree = q.get_subtree(db_path, root["id"], include_archived=True)
        names = {n["name"] for n in subtree}
        assert names == {"Active", "Archived"}


# ---------------------------------------------------------------------------
# move_node, rename_node
# ---------------------------------------------------------------------------

class TestMoveRename:
    def test_move_node(self, db_path):
        a = q.create_node(db_path, None, "A")
        b = q.create_node(db_path, None, "B")
        child = q.create_node(db_path, a["id"], "Child")

        q.move_node(db_path, child["id"], b["id"])
        moved = q.get_node(db_path, child["id"])
        assert moved["parent_id"] == b["id"]

    def test_rename_node(self, db_path):
        node = q.create_node(db_path, None, "OldName")
        q.rename_node(db_path, node["id"], "NewName")
        renamed = q.get_node(db_path, node["id"])
        assert renamed["name"] == "NewName"


# ---------------------------------------------------------------------------
# delete_node (cascade)
# ---------------------------------------------------------------------------

class TestDeleteNode:
    def test_delete_cascades_children(self, db_path):
        root = q.create_node(db_path, None, "Root")
        child = q.create_node(db_path, root["id"], "Child")
        q.create_node(db_path, child["id"], "Grandchild")

        q.delete_node(db_path, root["id"])
        assert q.get_node(db_path, root["id"]) is None
        assert q.get_node(db_path, child["id"]) is None

    def test_delete_cascades_sections(self, db_path):
        node = q.create_node(db_path, None, "X")
        q.upsert_section(db_path, node["id"], "details", "stuff")

        q.delete_node(db_path, node["id"])
        assert q.get_sections(db_path, node["id"]) == []

    def test_delete_cascades_task_links(self, db_path):
        node = q.create_node(db_path, None, "X")
        _insert_task(db_path, "t-1", "Task 1")
        q.link_task_to_node(db_path, node["id"], "t-1")

        q.delete_node(db_path, node["id"])
        assert q.get_task_nodes(db_path, "t-1") == []


# ---------------------------------------------------------------------------
# archive / unarchive
# ---------------------------------------------------------------------------

class TestArchive:
    def test_archive_and_unarchive(self, db_path):
        node = q.create_node(db_path, None, "X")
        assert q.get_node(db_path, node["id"])["archived"] == 0

        q.archive_node(db_path, node["id"])
        assert q.get_node(db_path, node["id"])["archived"] == 1

        q.unarchive_node(db_path, node["id"])
        assert q.get_node(db_path, node["id"])["archived"] == 0


# ---------------------------------------------------------------------------
# Section CRUD
# ---------------------------------------------------------------------------

class TestSections:
    def test_upsert_and_get(self, db_path):
        node = q.create_node(db_path, None, "Node")
        result = q.upsert_section(db_path, node["id"], "details", "Hello world")
        assert result["body"] == "Hello world"
        assert result["section_type"] == "details"

        fetched = q.get_section(db_path, node["id"], "details")
        assert fetched["body"] == "Hello world"

    def test_upsert_overwrites(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.upsert_section(db_path, node["id"], "details", "First")
        q.upsert_section(db_path, node["id"], "details", "Second")
        fetched = q.get_section(db_path, node["id"], "details")
        assert fetched["body"] == "Second"

    def test_get_all_sections(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.upsert_section(db_path, node["id"], "details", "D")
        q.upsert_section(db_path, node["id"], "notes", "N")
        sections = q.get_sections(db_path, node["id"])
        assert len(sections) == 2
        types = [s["section_type"] for s in sections]
        assert "details" in types
        assert "notes" in types

    def test_append_section_creates(self, db_path):
        node = q.create_node(db_path, None, "Node")
        result = q.append_section(db_path, node["id"], "log", "Entry 1")
        assert result["body"] == "Entry 1"

    def test_append_section_appends(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.upsert_section(db_path, node["id"], "log", "Entry 1")
        result = q.append_section(db_path, node["id"], "log", "Entry 2")
        assert result["body"] == "Entry 1\n\nEntry 2"

    def test_delete_section(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.upsert_section(db_path, node["id"], "details", "stuff")
        q.delete_section(db_path, node["id"], "details")
        assert q.get_section(db_path, node["id"], "details") is None

    def test_get_nonexistent_section(self, db_path):
        node = q.create_node(db_path, None, "Node")
        assert q.get_section(db_path, node["id"], "nope") is None


# ---------------------------------------------------------------------------
# search_sections (FTS5)
# ---------------------------------------------------------------------------

class TestSearchSections:
    def test_basic_search(self, db_path):
        n1 = q.create_node(db_path, None, "Alpha")
        n2 = q.create_node(db_path, None, "Beta")
        q.upsert_section(db_path, n1["id"], "details", "Machine learning project")
        q.upsert_section(db_path, n2["id"], "details", "Web development tasks")

        results = q.search_sections(db_path, "machine learning")
        assert len(results) == 1
        assert results[0]["node_id"] == n1["id"]
        assert "snippet" in results[0]

    def test_search_within_subtree(self, db_path):
        root = q.create_node(db_path, None, "Root")
        c1 = q.create_node(db_path, root["id"], "C1")
        c2 = q.create_node(db_path, root["id"], "C2")
        other = q.create_node(db_path, None, "Other")

        q.upsert_section(db_path, c1["id"], "details", "Important data here")
        q.upsert_section(db_path, c2["id"], "details", "More data there")
        q.upsert_section(db_path, other["id"], "details", "Unrelated data elsewhere")

        results = q.search_sections(db_path, "data", node_id=root["id"])
        node_ids = {r["node_id"] for r in results}
        assert c1["id"] in node_ids
        assert c2["id"] in node_ids
        assert other["id"] not in node_ids

    def test_search_no_results(self, db_path):
        node = q.create_node(db_path, None, "X")
        q.upsert_section(db_path, node["id"], "details", "Hello world")
        results = q.search_sections(db_path, "zzzznotfound")
        assert results == []


# ---------------------------------------------------------------------------
# link / unlink tasks
# ---------------------------------------------------------------------------

class TestNodeTasks:
    def test_link_and_get(self, db_path):
        node = q.create_node(db_path, None, "Proj")
        _insert_task(db_path, "t-1", "Build API")
        _insert_task(db_path, "t-2", "Write tests")

        q.link_task_to_node(db_path, node["id"], "t-1")
        q.link_task_to_node(db_path, node["id"], "t-2")

        tasks = q.get_node_tasks(db_path, node["id"])
        assert len(tasks) == 2
        ids = {t["id"] for t in tasks}
        assert ids == {"t-1", "t-2"}

    def test_unlink(self, db_path):
        node = q.create_node(db_path, None, "Proj")
        _insert_task(db_path, "t-1", "Build API")
        q.link_task_to_node(db_path, node["id"], "t-1")
        q.unlink_task_from_node(db_path, node["id"], "t-1")
        assert q.get_node_tasks(db_path, node["id"]) == []

    def test_link_idempotent(self, db_path):
        node = q.create_node(db_path, None, "Proj")
        _insert_task(db_path, "t-1", "Build API")
        q.link_task_to_node(db_path, node["id"], "t-1")
        q.link_task_to_node(db_path, node["id"], "t-1")  # no error
        assert len(q.get_node_tasks(db_path, node["id"])) == 1

    def test_get_task_nodes(self, db_path):
        n1 = q.create_node(db_path, None, "A")
        n2 = q.create_node(db_path, None, "B")
        _insert_task(db_path, "t-1", "Shared task")
        q.link_task_to_node(db_path, n1["id"], "t-1")
        q.link_task_to_node(db_path, n2["id"], "t-1")

        nodes = q.get_task_nodes(db_path, "t-1")
        assert len(nodes) == 2
        names = {n["name"] for n in nodes}
        assert names == {"A", "B"}


# ---------------------------------------------------------------------------
# get_milestone_nodes
# ---------------------------------------------------------------------------

class TestMilestoneNodes:
    def test_milestone_with_counts(self, db_path):
        parent = q.create_node(db_path, None, "Project")
        ms = q.create_node(
            db_path, parent["id"], "Beta Release",
            node_type="milestone", target_date="2026-07-01",
        )

        _insert_task(db_path, "t-1", "Task A", status="done")
        _insert_task(db_path, "t-2", "Task B", status="pending")
        _insert_task(db_path, "t-3", "Task C", status="done")

        q.link_task_to_node(db_path, ms["id"], "t-1")
        q.link_task_to_node(db_path, ms["id"], "t-2")
        q.link_task_to_node(db_path, ms["id"], "t-3")

        milestones = q.get_milestone_nodes(db_path, parent_id=parent["id"])
        assert len(milestones) == 1
        m = milestones[0]
        assert m["name"] == "Beta Release"
        assert m["task_count"] == 3
        assert m["done_count"] == 2

    def test_milestone_no_tasks(self, db_path):
        parent = q.create_node(db_path, None, "Project")
        q.create_node(
            db_path, parent["id"], "Empty MS", node_type="milestone",
        )
        milestones = q.get_milestone_nodes(db_path)
        assert len(milestones) == 1
        assert milestones[0]["task_count"] == 0
        assert milestones[0]["done_count"] == 0

    def test_excludes_context_nodes(self, db_path):
        parent = q.create_node(db_path, None, "Root")
        q.create_node(db_path, parent["id"], "Child", node_type="context")
        q.create_node(db_path, parent["id"], "MS", node_type="milestone")

        milestones = q.get_milestone_nodes(db_path, parent_id=parent["id"])
        assert len(milestones) == 1
        assert milestones[0]["name"] == "MS"

    def test_excludes_archived_by_default(self, db_path):
        parent = q.create_node(db_path, None, "Root")
        ms = q.create_node(db_path, parent["id"], "Old MS", node_type="milestone")
        q.archive_node(db_path, ms["id"])

        assert q.get_milestone_nodes(db_path, parent_id=parent["id"]) == []
        assert len(q.get_milestone_nodes(
            db_path, parent_id=parent["id"], include_archived=True
        )) == 1


# ---------------------------------------------------------------------------
# Named section files
# ---------------------------------------------------------------------------

class TestNamedSectionFiles:
    def test_upsert_section_with_name(self, db_path):
        node = q.create_node(db_path, None, "Node")
        result = q.upsert_section(db_path, node["id"], "notes", "Main notes")
        assert result["name"] == "main"
        assert result["body"] == "Main notes"

        result2 = q.upsert_section(db_path, node["id"], "notes", "Ideas", name="ideas")
        assert result2["name"] == "ideas"
        assert result2["body"] == "Ideas"

        # Both should coexist
        sections = q.get_sections(db_path, node["id"])
        assert len(sections) == 2
        names = {s["name"] for s in sections}
        assert names == {"main", "ideas"}

        # get_section with default name still returns the 'main' one
        main = q.get_section(db_path, node["id"], "notes")
        assert main["body"] == "Main notes"

        # get_section with explicit name
        ideas = q.get_section(db_path, node["id"], "notes", name="ideas")
        assert ideas["body"] == "Ideas"

    def test_list_section_files(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.upsert_section(db_path, node["id"], "notes", "File A content", name="a")
        q.upsert_section(db_path, node["id"], "notes", "File B longer content", name="b")

        files = q.list_section_files(db_path, node["id"], "notes")
        assert len(files) == 2
        # Check returned fields
        for f in files:
            assert "name" in f
            assert "size" in f
            assert "updated_at" in f
            assert "position" in f
            # body should NOT be in the result
            assert "body" not in f

        names = [f["name"] for f in files]
        assert "a" in names
        assert "b" in names

        # size should be character count of body
        a_file = next(f for f in files if f["name"] == "a")
        assert a_file["size"] == len("File A content")

    def test_create_section_file(self, db_path):
        node = q.create_node(db_path, None, "Node")
        result = q.create_section_file(db_path, node["id"], "notes", "readme")
        assert result["name"] == "readme"
        assert result["body"] == ""
        assert result["position"] == 0

        result2 = q.create_section_file(db_path, node["id"], "notes", "changelog", body="v1.0")
        assert result2["name"] == "changelog"
        assert result2["body"] == "v1.0"
        assert result2["position"] == 1

        # Verify we can read them back
        fetched = q.get_section(db_path, node["id"], "notes", name="readme")
        assert fetched is not None
        assert fetched["body"] == ""

        fetched2 = q.get_section(db_path, node["id"], "notes", name="changelog")
        assert fetched2["body"] == "v1.0"

    def test_create_section_file_duplicate_raises(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.create_section_file(db_path, node["id"], "notes", "readme")
        with pytest.raises(sqlite3.IntegrityError):
            q.create_section_file(db_path, node["id"], "notes", "readme")

    def test_rename_section_file(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.create_section_file(db_path, node["id"], "notes", "old_name", body="content")

        result = q.rename_section_file(db_path, node["id"], "notes", "old_name", "new_name")
        assert result["name"] == "new_name"
        assert result["body"] == "content"

        # Old name should be gone
        assert q.get_section(db_path, node["id"], "notes", name="old_name") is None

    def test_rename_section_file_missing_raises(self, db_path):
        node = q.create_node(db_path, None, "Node")
        with pytest.raises(ValueError, match="not found"):
            q.rename_section_file(db_path, node["id"], "notes", "nonexistent", "new")

    def test_reorder_section_files(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.create_section_file(db_path, node["id"], "notes", "a")
        q.create_section_file(db_path, node["id"], "notes", "b")
        q.create_section_file(db_path, node["id"], "notes", "c")

        # Reorder: c, a, b
        q.reorder_section_files(db_path, node["id"], "notes", ["c", "a", "b"])

        files = q.list_section_files(db_path, node["id"], "notes")
        names_in_order = [f["name"] for f in files]
        assert names_in_order == ["c", "a", "b"]

    def test_search_includes_name(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.upsert_section(db_path, node["id"], "notes", "important search text", name="ideas")

        results = q.search_sections(db_path, "important search")
        assert len(results) == 1
        assert results[0]["name"] == "ideas"
        assert results[0]["section_type"] == "notes"

    def test_append_section_with_name(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.upsert_section(db_path, node["id"], "log", "Entry 1", name="daily")
        result = q.append_section(db_path, node["id"], "log", "Entry 2", name="daily")
        assert result["body"] == "Entry 1\n\nEntry 2"
        assert result["name"] == "daily"

    def test_delete_section_with_name(self, db_path):
        node = q.create_node(db_path, None, "Node")
        q.upsert_section(db_path, node["id"], "notes", "Main", name="main")
        q.upsert_section(db_path, node["id"], "notes", "Extra", name="extra")

        q.delete_section(db_path, node["id"], "notes", name="extra")
        # main should still exist
        assert q.get_section(db_path, node["id"], "notes", name="main") is not None
        # extra should be gone
        assert q.get_section(db_path, node["id"], "notes", name="extra") is None


# ---------------------------------------------------------------------------
# Node description
# ---------------------------------------------------------------------------

class TestNodeDescription:
    def test_patch_node_fields_with_description(self, db_path):
        node = q.create_node(db_path, None, "MyNode")
        assert node["description"] is None

        updated = q.patch_node_fields(db_path, node["id"], {"description": "A useful desc"})
        assert updated["description"] == "A useful desc"

    def test_get_node_returns_description(self, db_path):
        node = q.create_node(db_path, None, "MyNode")
        q.patch_node_fields(db_path, node["id"], {"description": "Hello there"})

        fetched = q.get_node(db_path, node["id"])
        assert fetched["description"] == "Hello there"

    def test_create_node_has_null_description(self, db_path):
        node = q.create_node(db_path, None, "MyNode")
        fetched = q.get_node(db_path, node["id"])
        assert fetched["description"] is None
