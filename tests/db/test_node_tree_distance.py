"""Tests for get_node_tree_distance — the consolidated bounded-BFS distance query.

Uses mocked asyncpg connections (no live Postgres required). This is the SOLE
distance query, consolidated from two prior implementations: the deleted
unbounded LCA-walk get_node_hop_distance (nodes.py) and the deleted
single-root bounded-BFS get_node_tree_distance (node_memory.py) — this
version lives in nodes.py, generalized to multi-root (from_ids: list[str],
min-distance-wins per DD §5.8's multi-root org-accounts model).

The SQL logic itself is verified end-to-end in test_pg_nodes.py (requires
DATABASE_URL); these tests verify the Python-level contract: the from_id==to_id
short-circuit, multi-root membership short-circuit, return-value passthrough,
and that both UUIDs/bound are threaded to the query correctly.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from db.pg_queries.nodes import get_node_tree_distance


_A = "00000000-0000-0000-0000-000000000001"
_B = "00000000-0000-0000-0000-000000000002"
_C = "00000000-0000-0000-0000-000000000003"


def _mock_conn(fetchrow_return: dict | None):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    return conn


# ---------------------------------------------------------------------------
# Short-circuits — no DB round trip
# ---------------------------------------------------------------------------


async def test_to_id_equals_only_from_id_returns_zero_without_query():
    conn = _mock_conn(None)
    result = await get_node_tree_distance(conn, [_A], _A, max_N=5)
    assert result == 0
    conn.fetchrow.assert_not_called()


async def test_to_id_is_one_of_multiple_from_ids_returns_zero_without_query():
    """Multi-root: to_id matching ANY root is distance 0, no query needed."""
    conn = _mock_conn(None)
    result = await get_node_tree_distance(conn, [_A, _B], _B, max_N=5)
    assert result == 0
    conn.fetchrow.assert_not_called()


# ---------------------------------------------------------------------------
# Query path — value passthrough
# ---------------------------------------------------------------------------


async def test_returns_distance_from_query_row():
    conn = _mock_conn({"dist": 2})
    result = await get_node_tree_distance(conn, [_A], _C, max_N=5)
    assert result == 2


async def test_returns_none_when_no_row():
    """No row (empty CTE result) → out of bound / unreachable."""
    conn = _mock_conn(None)
    result = await get_node_tree_distance(conn, [_A], _C, max_N=5)
    assert result is None


async def test_returns_none_when_dist_is_none():
    """Row exists but dist is NULL (e.g. MIN() over empty set) → None."""
    conn = _mock_conn({"dist": None})
    result = await get_node_tree_distance(conn, [_A], _C, max_N=5)
    assert result is None


# ---------------------------------------------------------------------------
# Query contract — args threaded correctly
# ---------------------------------------------------------------------------


async def test_fetchrow_called_with_uuid_list_and_bound():
    conn = _mock_conn({"dist": 1})
    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())

    await get_node_tree_distance(conn, [from_id], to_id, max_N=7)

    conn.fetchrow.assert_called_once()
    call_args = conn.fetchrow.call_args
    positional = call_args.args if call_args.args else call_args[0]
    assert positional[1] == [uuid.UUID(from_id)]
    assert positional[2] == uuid.UUID(to_id)
    assert positional[3] == 7


async def test_multi_root_from_ids_all_passed_as_uuid_list():
    conn = _mock_conn({"dist": 3})
    a, b, c = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    to_id = str(uuid.uuid4())

    await get_node_tree_distance(conn, [a, b, c], to_id, max_N=5)

    call_args = conn.fetchrow.call_args
    positional = call_args.args if call_args.args else call_args[0]
    assert positional[1] == [uuid.UUID(a), uuid.UUID(b), uuid.UUID(c)]
