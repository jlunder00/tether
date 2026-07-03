"""Tests for get_node_hop_distance — uses mocked asyncpg connection.

All tests run without a live Postgres instance (no DATABASE_URL required).
The SQL logic is verified end-to-end in test_pg_nodes.py (requires DATABASE_URL).
"""
from __future__ import annotations

import decimal
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from db.pg_queries.nodes import get_node_hop_distance


# Stable test UUIDs — use fixed values so failures are easy to read
_A = "00000000-0000-0000-0000-000000000001"
_B = "00000000-0000-0000-0000-000000000002"
_C = "00000000-0000-0000-0000-000000000003"
_D = "00000000-0000-0000-0000-000000000004"


def _mock_conn(fetchval_return):
    """Return a mock asyncpg Connection that returns a preset value from fetchval."""
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=fetchval_return)
    return conn


# ---------------------------------------------------------------------------
# Basic distance cases
# ---------------------------------------------------------------------------


async def test_same_node_returns_zero():
    """A node is 0 hops from itself (LCA is itself, both depths=0)."""
    conn = _mock_conn(0)
    result = await get_node_hop_distance(conn, _A, _A)
    assert result == 0


async def test_direct_parent_child_returns_one():
    """Parent → child is 1 hop."""
    conn = _mock_conn(1)
    result = await get_node_hop_distance(conn, _A, _B)
    assert result == 1


async def test_grandparent_to_grandchild_returns_two():
    """Grandparent → grandchild is 2 hops."""
    conn = _mock_conn(2)
    result = await get_node_hop_distance(conn, _A, _C)
    assert result == 2


async def test_sibling_returns_two():
    """Two siblings share a common parent → 2 undirected hops (via parent)."""
    conn = _mock_conn(2)
    result = await get_node_hop_distance(conn, _B, _C)
    assert result == 2


async def test_cousins_return_four():
    """Cousins: each 2 hops from their common grandparent → 4 hops total."""
    conn = _mock_conn(4)
    result = await get_node_hop_distance(conn, _C, _D)
    assert result == 4


# ---------------------------------------------------------------------------
# Unrelated nodes
# ---------------------------------------------------------------------------


async def test_unrelated_nodes_returns_none():
    """Nodes in separate trees (no common ancestor) → None."""
    conn = _mock_conn(None)
    result = await get_node_hop_distance(conn, _A, _D)
    assert result is None


# ---------------------------------------------------------------------------
# Return type coercion
# ---------------------------------------------------------------------------


async def test_returns_int_not_decimal():
    """Result from DB (may be Decimal/numeric) is coerced to Python int."""
    conn = _mock_conn(decimal.Decimal("3"))
    result = await get_node_hop_distance(conn, _A, _B)
    assert result == 3
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# Query contract — both UUIDs passed to fetchval
# ---------------------------------------------------------------------------


async def test_fetchval_called_with_both_uuid_args():
    """The function passes both node IDs as uuid.UUID objects to fetchval."""
    conn = _mock_conn(1)
    from_id = str(uuid.uuid4())
    to_id = str(uuid.uuid4())

    await get_node_hop_distance(conn, from_id, to_id)

    conn.fetchval.assert_called_once()
    call_args = conn.fetchval.call_args
    # positional args after the SQL string should include the two UUIDs
    positional = call_args.args if call_args.args else call_args[0]
    assert uuid.UUID(from_id) in positional
    assert uuid.UUID(to_id) in positional
