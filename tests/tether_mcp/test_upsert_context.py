"""Tests for the upsert_context tool (Task 6 of MCP Interface Consolidation)."""
import os
import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import (
    create_node,
    get_node,
    get_node_by_path,
    get_section,
    upsert_section,
    find_child_by_name,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture(autouse=True)
def set_db_env(db_path):
    os.environ["TETHER_DB_PATH"] = str(db_path)
    yield
    del os.environ["TETHER_DB_PATH"]


# ---------------------------------------------------------------------------
# 1. Create single node by name
# ---------------------------------------------------------------------------

def test_create_single_node():
    from tether_mcp.tools.upsert_context import execute_upsert_context
    results = execute_upsert_context([{"name": "Projects"}])
    assert len(results) == 1
    r = results[0]
    assert r["name"] == "Projects"
    assert r["path"] == "Projects"
    assert r["action"] == "created"
    assert r["node_type"] == "context"
    assert r["id"]


# ---------------------------------------------------------------------------
# 2. Create path with intermediates (A/B/C)
# ---------------------------------------------------------------------------

def test_create_path_with_intermediates(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    results = execute_upsert_context([{"name": "A/B/C"}])
    # Three nodes created: one result entry for the final node
    assert len(results) == 1
    r = results[0]
    assert r["name"] == "C"
    assert r["path"] == "A/B/C"
    assert r["action"] == "created"

    # Verify intermediates exist
    a = get_node_by_path(db_path, "A")
    b = get_node_by_path(db_path, "A/B")
    c = get_node_by_path(db_path, "A/B/C")
    assert a is not None
    assert b is not None
    assert c is not None


# ---------------------------------------------------------------------------
# 3. Update existing node (description change)
# ---------------------------------------------------------------------------

def test_update_existing_node_description(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    node = create_node(db_path, None, "ExistingNode")

    results = execute_upsert_context([{
        "name": "ExistingNode",
        "description": "Updated description",
    }])
    assert len(results) == 1
    r = results[0]
    assert r["action"] == "updated"

    updated = get_node(db_path, node["id"])
    assert updated["description"] == "Updated description"


# ---------------------------------------------------------------------------
# 4. Named section files
# ---------------------------------------------------------------------------

def test_named_section_files(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    results = execute_upsert_context([{
        "name": "MyProject",
        "sections": {
            "details": {
                "main": "Main content here",
                "arch": "Architecture notes",
            }
        },
    }])
    assert len(results) == 1
    node_id = results[0]["id"]

    main_sec = get_section(db_path, node_id, "details", "main")
    arch_sec = get_section(db_path, node_id, "details", "arch")
    assert main_sec is not None
    assert main_sec["body"] == "Main content here"
    assert arch_sec is not None
    assert arch_sec["body"] == "Architecture notes"


# ---------------------------------------------------------------------------
# 5. Section append mode
# ---------------------------------------------------------------------------

def test_section_append_mode(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    node = create_node(db_path, None, "AppendNode")
    upsert_section(db_path, node["id"], "notes", "First line", name="main")

    execute_upsert_context([{
        "name": "AppendNode",
        "sections": {
            "notes": {
                "main": {"mode": "append", "value": "Second line"},
            }
        },
    }])

    sec = get_section(db_path, node["id"], "notes", "main")
    assert sec["body"] == "First line\nSecond line"


# ---------------------------------------------------------------------------
# 6. Section patch find-replace mode
# ---------------------------------------------------------------------------

def test_section_patch_find_replace(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    node = create_node(db_path, None, "PatchNode")
    upsert_section(db_path, node["id"], "details", "Hello world", name="main")

    execute_upsert_context([{
        "name": "PatchNode",
        "sections": {
            "details": {
                "main": {
                    "mode": "patch",
                    "operations": [{"find": "world", "replace": "tether"}],
                },
            }
        },
    }])

    sec = get_section(db_path, node["id"], "details", "main")
    assert sec["body"] == "Hello tether"


# ---------------------------------------------------------------------------
# 7. Section patch line-replace mode
# ---------------------------------------------------------------------------

def test_section_patch_line_replace(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    node = create_node(db_path, None, "LineNode")
    upsert_section(db_path, node["id"], "details", "line one\nline two\nline three", name="main")

    execute_upsert_context([{
        "name": "LineNode",
        "sections": {
            "details": {
                "main": {
                    "mode": "patch",
                    "operations": [{"lines": [2], "replace": "REPLACED"}],
                },
            }
        },
    }])

    sec = get_section(db_path, node["id"], "details", "main")
    assert sec["body"] == "line one\nREPLACED\nline three"


# ---------------------------------------------------------------------------
# 8. Children recursive creation
# ---------------------------------------------------------------------------

def test_children_recursive_creation(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    results = execute_upsert_context([{
        "name": "Parent",
        "children": [
            {"name": "Child1"},
            {"name": "Child2", "children": [
                {"name": "Grandchild"},
            ]},
        ],
    }])

    # Results should be flat: Parent, Child1, Child2, Grandchild
    assert len(results) == 4
    names = [r["name"] for r in results]
    assert "Parent" in names
    assert "Child1" in names
    assert "Child2" in names
    assert "Grandchild" in names

    # Verify paths
    paths = {r["name"]: r["path"] for r in results}
    assert paths["Child1"] == "Parent/Child1"
    assert paths["Grandchild"] == "Parent/Child2/Grandchild"


# ---------------------------------------------------------------------------
# 9. node_id direct lookup + update
# ---------------------------------------------------------------------------

def test_node_id_direct_lookup_and_update(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    node = create_node(db_path, None, "DirectNode")

    results = execute_upsert_context([{
        "node_id": node["id"],
        "description": "Set via node_id",
    }])
    assert len(results) == 1
    r = results[0]
    assert r["id"] == node["id"]
    assert r["action"] == "updated"

    updated = get_node(db_path, node["id"])
    assert updated["description"] == "Set via node_id"


def test_node_id_with_rename(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    node = create_node(db_path, None, "OldName")

    results = execute_upsert_context([{
        "node_id": node["id"],
        "name": "NewName",
    }])
    assert len(results) == 1
    updated = get_node(db_path, node["id"])
    assert updated["name"] == "NewName"


# ---------------------------------------------------------------------------
# 10. Reparent via `parent` field
# ---------------------------------------------------------------------------

def test_reparent_via_parent_field(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    parent_a = create_node(db_path, None, "ParentA")
    parent_b = create_node(db_path, None, "ParentB")
    child = create_node(db_path, parent_a["id"], "ChildNode")

    # Move child from ParentA to ParentB using parent field with path
    results = execute_upsert_context([{
        "node_id": child["id"],
        "parent": "ParentB",
    }])
    assert len(results) == 1
    r = results[0]
    assert r["action"] == "moved"

    updated = get_node(db_path, child["id"])
    assert updated["parent_id"] == parent_b["id"]


def test_reparent_to_root(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    parent = create_node(db_path, None, "SomeParent")
    child = create_node(db_path, parent["id"], "ToBeRoot")

    execute_upsert_context([{
        "node_id": child["id"],
        "parent": "",
    }])

    updated = get_node(db_path, child["id"])
    assert updated["parent_id"] is None


# ---------------------------------------------------------------------------
# 11. Idempotent (call twice = second time "updated")
# ---------------------------------------------------------------------------

def test_idempotent_create_then_update(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context

    r1 = execute_upsert_context([{"name": "Idempotent"}])
    assert r1[0]["action"] == "created"

    r2 = execute_upsert_context([{"name": "Idempotent"}])
    assert r2[0]["action"] == "updated"
    # Same node id returned both times
    assert r1[0]["id"] == r2[0]["id"]


# ---------------------------------------------------------------------------
# 12. Mixed patch ops in section → MixedPatchOpsError
# ---------------------------------------------------------------------------

def test_mixed_patch_ops_raises(db_path):
    from tether_mcp.tools.upsert_context import execute_upsert_context
    from tether_mcp.write_modes import MixedPatchOpsError

    node = create_node(db_path, None, "MixedNode")
    upsert_section(db_path, node["id"], "notes", "some text", name="main")

    with pytest.raises(MixedPatchOpsError):
        execute_upsert_context([{
            "name": "MixedNode",
            "sections": {
                "notes": {
                    "main": {
                        "mode": "patch",
                        "operations": [
                            {"find": "some", "replace": "other"},
                            {"lines": [1], "replace": "replaced"},
                        ],
                    },
                }
            },
        }])
