"""Tests for tether_mcp.batch — duplicate detection and topological sort."""

import pytest
from tether_mcp.batch import CircularDependencyError, validate_no_duplicates, topological_sort


# ---------------------------------------------------------------------------
# validate_no_duplicates
# ---------------------------------------------------------------------------

class TestValidateNoDuplicates:
    def test_no_duplicates_passes(self):
        specs = [
            {"task_uuid": "aaa", "title": "A"},
            {"task_uuid": "bbb", "title": "B"},
            {"task_uuid": "ccc", "title": "C"},
        ]
        # Should not raise
        validate_no_duplicates(specs, "task_uuid")

    def test_duplicate_raises_with_message(self):
        specs = [
            {"task_uuid": "abc-123", "title": "A"},
            {"task_uuid": "bbb", "title": "B"},
            {"task_uuid": "abc-123", "title": "A-dup"},
        ]
        with pytest.raises(ValueError, match="Duplicate task_uuid in batch: abc-123"):
            validate_no_duplicates(specs, "task_uuid")

    def test_empty_key_values_are_ignored(self):
        specs = [
            {"task_uuid": "", "title": "new-1"},
            {"task_uuid": "", "title": "new-2"},
            {"task_uuid": "real-id", "title": "existing"},
        ]
        # Empty strings should be ignored — no error
        validate_no_duplicates(specs, "task_uuid")

    def test_missing_key_treated_as_empty(self):
        specs = [
            {"title": "no-uuid-1"},
            {"title": "no-uuid-2"},
        ]
        # Missing key behaves like empty string — ignored
        validate_no_duplicates(specs, "task_uuid")

    def test_single_spec_passes(self):
        specs = [{"task_uuid": "only-one"}]
        validate_no_duplicates(specs, "task_uuid")

    def test_empty_list_passes(self):
        validate_no_duplicates([], "task_uuid")


# ---------------------------------------------------------------------------
# topological_sort
# ---------------------------------------------------------------------------

class TestTopologicalSort:
    def test_no_deps_preserves_order(self):
        specs = [
            {"id": "a", "title": "A"},
            {"id": "b", "title": "B"},
            {"id": "c", "title": "C"},
        ]
        result = topological_sort(specs, id_key="id")
        assert [s["id"] for s in result] == ["a", "b", "c"]

    def test_simple_dependency_a_before_b(self):
        # B depends on A — A must come first
        specs = [
            {"id": "b", "deps": ["a"]},
            {"id": "a", "deps": []},
        ]
        result = topological_sort(specs, id_key="id", deps_key="deps")
        ids = [s["id"] for s in result]
        assert ids.index("a") < ids.index("b")

    def test_chain_a_b_c(self):
        # C depends on B, B depends on A
        specs = [
            {"id": "c", "deps": ["b"]},
            {"id": "b", "deps": ["a"]},
            {"id": "a", "deps": []},
        ]
        result = topological_sort(specs, id_key="id", deps_key="deps")
        ids = [s["id"] for s in result]
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")

    def test_circular_raises_error(self):
        specs = [
            {"id": "a", "deps": ["b"]},
            {"id": "b", "deps": ["a"]},
        ]
        with pytest.raises(CircularDependencyError):
            topological_sort(specs, id_key="id", deps_key="deps")

    def test_circular_error_lists_cycle_members(self):
        specs = [
            {"id": "x", "deps": ["y"]},
            {"id": "y", "deps": ["x"]},
        ]
        with pytest.raises(CircularDependencyError) as exc_info:
            topological_sort(specs, id_key="id", deps_key="deps")
        msg = str(exc_info.value)
        assert "x" in msg or "y" in msg

    def test_external_deps_ignored(self):
        # "external-id" is not in the batch — should be silently ignored
        specs = [
            {"id": "a", "deps": ["external-id"]},
            {"id": "b", "deps": ["a"]},
        ]
        result = topological_sort(specs, id_key="id", deps_key="deps")
        ids = [s["id"] for s in result]
        assert ids.index("a") < ids.index("b")

    def test_multiple_independent_specs_stay_ordered(self):
        # No dependencies — all independent specs keep original order
        specs = [
            {"id": "x"},
            {"id": "y"},
            {"id": "z"},
        ]
        result = topological_sort(specs, id_key="id")
        assert [s["id"] for s in result] == ["x", "y", "z"]

    def test_empty_list(self):
        result = topological_sort([], id_key="id")
        assert result == []

    def test_single_spec_no_deps(self):
        specs = [{"id": "solo"}]
        result = topological_sort(specs, id_key="id")
        assert result == specs

    def test_deps_key_default_is_deps(self):
        specs = [
            {"id": "b", "deps": ["a"]},
            {"id": "a"},
        ]
        # Should work using default deps_key="deps"
        result = topological_sort(specs, id_key="id")
        ids = [s["id"] for s in result]
        assert ids.index("a") < ids.index("b")

    def test_freed_at_different_stages_preserve_original_order(self):
        specs = [
            {"id": "a"},
            {"id": "c", "deps": ["b"]},
            {"id": "b", "deps": ["a"]},
            {"id": "d", "deps": ["a"]},
        ]
        result = topological_sort(specs, id_key="id", deps_key="deps")
        ids = [s["id"] for s in result]
        # a must come first (only seed). Then b and d (freed by a).
        # c and d have no relationship but c (idx 1) should come before d (idx 3) in original order.
        assert ids.index("a") == 0
        assert ids.index("b") < ids.index("c")  # b blocks c
        assert ids.index("c") < ids.index("d")  # c (idx 1) before d (idx 3) by original order
