"""Tests for the read_context tool (Task 3 of MCP Interface Consolidation)."""
import os
import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import (
    create_node,
    upsert_section,
    link_task_to_node,
    create_unscheduled_task,
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


@pytest.fixture
def sample_data(db_path):
    """Create a tree: Projects (root) -> Tether (context) -> Phase 9 (milestone).
    Add sections and a task on Tether.
    """
    projects = create_node(db_path, None, "Projects", node_type="context")
    tether = create_node(db_path, projects["id"], "Tether", node_type="context")
    phase9 = create_node(db_path, tether["id"], "Phase 9", node_type="milestone")

    # Add two sections to Tether
    upsert_section(db_path, tether["id"], "details", "Line one\nLine two\nLine three", name="main")
    upsert_section(db_path, tether["id"], "details", "Architecture notes here", name="arch")

    # Link a task to Tether
    task = create_unscheduled_task(db_path, "Implement read_context", status="pending")
    link_task_to_node(db_path, tether["id"], task["id"])

    return {
        "projects": projects,
        "tether": tether,
        "phase9": phase9,
        "task": task,
    }


# ---------------------------------------------------------------------------
# 1. No params → returns root nodes
# ---------------------------------------------------------------------------

def test_no_params_returns_root_nodes(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    result = execute_read_context()
    assert result is not None
    assert len(result) >= 1
    names = [n["name"] for n in result if n is not None]
    assert "Projects" in names


# ---------------------------------------------------------------------------
# 2. By path → returns correct node
# ---------------------------------------------------------------------------

def test_by_path_returns_correct_node(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    result = execute_read_context(paths=["Projects/Tether"])
    assert len(result) == 1
    node = result[0]
    assert node is not None
    assert node["name"] == "Tether"
    assert node["id"] == sample_data["tether"]["id"]


# ---------------------------------------------------------------------------
# 3. By node_id → returns correct node
# ---------------------------------------------------------------------------

def test_by_node_id_returns_correct_node(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    node_id = sample_data["tether"]["id"]
    result = execute_read_context(node_ids=[node_id])
    assert len(result) == 1
    node = result[0]
    assert node is not None
    assert node["name"] == "Tether"
    assert node["id"] == node_id


# ---------------------------------------------------------------------------
# 4. depth=1 → includes children
# ---------------------------------------------------------------------------

def test_depth_1_includes_children(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    node_id = sample_data["tether"]["id"]
    result = execute_read_context(node_ids=[node_id], depth=1)
    assert len(result) == 1
    node = result[0]
    assert "children" in node
    child_names = [c["name"] for c in node["children"]]
    assert "Phase 9" in child_names


# ---------------------------------------------------------------------------
# 5. depth=0 → no children key
# ---------------------------------------------------------------------------

def test_depth_0_no_children_key(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    node_id = sample_data["tether"]["id"]
    result = execute_read_context(node_ids=[node_id], depth=0)
    assert len(result) == 1
    node = result[0]
    assert "children" not in node


# ---------------------------------------------------------------------------
# 6. include_sections → sections in cat-n format with line_count
# ---------------------------------------------------------------------------

def test_include_sections_cat_n_format(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    node_id = sample_data["tether"]["id"]
    result = execute_read_context(node_ids=[node_id], include_sections=True)
    assert len(result) == 1
    node = result[0]
    assert "sections" in node
    assert "details" in node["sections"]
    details_files = node["sections"]["details"]
    assert len(details_files) == 2

    # Find "main" file
    main_file = next(f for f in details_files if f["name"] == "main")
    # Body should be in cat -n format
    assert main_file["body"].startswith("1\t")
    assert "\t" in main_file["body"]
    assert "line_count" in main_file
    assert main_file["line_count"] == 3  # "Line one\nLine two\nLine three" = 3 lines

    # Find "arch" file
    arch_file = next(f for f in details_files if f["name"] == "arch")
    assert arch_file["body"].startswith("1\t")
    assert arch_file["line_count"] == 1


# ---------------------------------------------------------------------------
# 7. include_tasks → linked tasks included
# ---------------------------------------------------------------------------

def test_include_tasks(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    node_id = sample_data["tether"]["id"]
    result = execute_read_context(node_ids=[node_id], include_tasks=True)
    assert len(result) == 1
    node = result[0]
    assert "tasks" in node
    task_texts = [t["text"] for t in node["tasks"]]
    assert "Implement read_context" in task_texts


# ---------------------------------------------------------------------------
# 8. Nonexistent path → None in result list
# ---------------------------------------------------------------------------

def test_nonexistent_path_returns_none(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    result = execute_read_context(paths=["Nonexistent/Path"])
    assert len(result) == 1
    assert result[0] is None


def test_nonexistent_node_id_returns_none():
    from tether_mcp.tools.read_context import execute_read_context
    result = execute_read_context(node_ids=["00000000-0000-0000-0000-000000000000"])
    assert len(result) == 1
    assert result[0] is None


# ---------------------------------------------------------------------------
# 9. Roots with depth=1 → roots with their children
# ---------------------------------------------------------------------------

def test_roots_with_depth_1(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    result = execute_read_context(depth=1)
    assert result is not None
    # Find the "Projects" root
    projects_node = next((n for n in result if n and n["name"] == "Projects"), None)
    assert projects_node is not None
    assert "children" in projects_node
    child_names = [c["name"] for c in projects_node["children"]]
    assert "Tether" in child_names


# ---------------------------------------------------------------------------
# Additional: depth=-1 gives full subtree
# ---------------------------------------------------------------------------

def test_depth_minus_1_full_subtree(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    node_id = sample_data["projects"]["id"]
    result = execute_read_context(node_ids=[node_id], depth=-1)
    assert len(result) == 1
    node = result[0]
    assert "children" in node
    tether_node = next((c for c in node["children"] if c["name"] == "Tether"), None)
    assert tether_node is not None
    # Tether should have its children too (Phase 9)
    assert "children" in tether_node
    phase9_names = [c["name"] for c in tether_node["children"]]
    assert "Phase 9" in phase9_names


# ---------------------------------------------------------------------------
# Multiple node_ids → results in same order as input
# ---------------------------------------------------------------------------

def test_multiple_node_ids_order(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    tether_id = sample_data["tether"]["id"]
    phase9_id = sample_data["phase9"]["id"]
    result = execute_read_context(node_ids=[phase9_id, tether_id])
    assert len(result) == 2
    assert result[0]["id"] == phase9_id
    assert result[1]["id"] == tether_id


# ---------------------------------------------------------------------------
# Multiple paths → results in same order as input
# ---------------------------------------------------------------------------

def test_multiple_paths_order(sample_data):
    from tether_mcp.tools.read_context import execute_read_context
    result = execute_read_context(paths=["Projects/Tether/Phase 9", "Projects/Tether"])
    assert len(result) == 2
    assert result[0]["name"] == "Phase 9"
    assert result[1]["name"] == "Tether"
