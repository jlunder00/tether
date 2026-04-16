"""Batch validation and dependency resolution for MCP upsert tools.

Provides:
- validate_no_duplicates: checks that no two specs share the same non-empty key value
- topological_sort: orders specs so dependencies come before dependents (Kahn's algorithm)
"""

from __future__ import annotations

import heapq


class CircularDependencyError(ValueError):
    """Raised when a cycle is detected in the dependency graph."""


def validate_no_duplicates(specs: list[dict], key: str) -> None:
    """Check that no two specs share the same non-empty value for *key*.

    Empty string values (and missing keys) are treated as "no ID yet" and
    are silently skipped.

    Raises:
        ValueError: with a message like "Duplicate task_uuid in batch: abc-123"
    """
    seen: set[str] = set()
    for spec in specs:
        value = spec.get(key, "")
        if not value:
            continue
        if value in seen:
            raise ValueError(f"Duplicate {key} in batch: {value}")
        seen.add(value)


def topological_sort(
    specs: list[dict],
    id_key: str,
    deps_key: str = "deps",
) -> list[dict]:
    """Return *specs* in topological order (dependencies before dependents).

    Only intra-batch dependencies are considered; references to IDs not
    present in the batch are ignored.

    Uses Kahn's algorithm to produce a stable sort: nodes with in-degree 0
    are processed in their original list order, so specs without dependencies
    preserve their original relative order.

    Raises:
        CircularDependencyError: if a cycle is detected, listing cycle members.
    """
    if not specs:
        return []

    # Map id → original index and spec
    id_to_idx: dict[str, int] = {}
    for i, spec in enumerate(specs):
        node_id = spec.get(id_key, "")
        if node_id:
            id_to_idx[node_id] = i

    batch_ids: set[str] = set(id_to_idx.keys())

    # Build adjacency list and in-degree count (only intra-batch edges)
    # adjacency[i] = list of indices that depend on i (i must come before them)
    n = len(specs)
    in_degree = [0] * n
    adjacency: list[list[int]] = [[] for _ in range(n)]

    for i, spec in enumerate(specs):
        raw_deps = spec.get(deps_key) or []
        for dep_id in raw_deps:
            if dep_id in batch_ids:
                dep_idx = id_to_idx[dep_id]
                adjacency[dep_idx].append(i)
                in_degree[i] += 1

    # Kahn's algorithm — use a min-heap keyed on original index to preserve order
    heap: list[int] = [i for i in range(n) if in_degree[i] == 0]
    heapq.heapify(heap)

    result: list[dict] = []
    while heap:
        idx = heapq.heappop(heap)
        result.append(specs[idx])
        for neighbor in adjacency[idx]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                heapq.heappush(heap, neighbor)

    if len(result) != n:
        # Cycle detected — collect remaining nodes for the error message
        cycle_members = [
            specs[i].get(id_key, f"<spec[{i}]>")
            for i in range(n)
            if in_degree[i] > 0
        ]
        raise CircularDependencyError(
            f"Circular dependency detected among batch specs: {cycle_members}"
        )

    return result
