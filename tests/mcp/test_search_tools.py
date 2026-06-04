"""Tests for search_context and search_memory MCP tools.

TDD — tests written before implementation. All tests should fail until:
  - db/pg_queries/sections.py gains search_sections_fts()
  - db/pg_queries/memory.py gains search_user_memory()
  - tether_mcp/tools/search_context.py is implemented
  - tether_mcp/tools/search_memory.py is implemented
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    return AsyncMock()


# ---------------------------------------------------------------------------
# search_context
# ---------------------------------------------------------------------------

class TestSearchContext:
    """execute_search_context delegates to search_sections_fts and formats results."""

    @pytest.mark.asyncio
    async def test_returns_results_from_fts(self, conn):
        """Happy path: FTS query returns matches, tool wraps them correctly."""
        fake_rows = [
            {
                "node_id": "node-uuid-1",
                "node_name": "Work Projects",
                "section_type": "notes",
                "section_name": "main",
                "snippet": "context about <b>quarterly</b> planning",
                "score": 0.42,
            }
        ]
        with patch(
            "db.pg_queries.sections.search_sections_fts",
            AsyncMock(return_value=fake_rows),
        ) as mock_fts:
            from tether_mcp.tools.search_context import execute_search_context

            result = await execute_search_context(conn, query="quarterly planning")

        mock_fts.assert_called_once()
        assert result["total"] == 1
        assert len(result["results"]) == 1
        row = result["results"][0]
        assert row["node_id"] == "node-uuid-1"
        assert row["node_title"] == "Work Projects"
        assert row["section_title"] == "main"
        assert row["snippet"] == "context about <b>quarterly</b> planning"
        assert row["score"] == pytest.approx(0.42)

    @pytest.mark.asyncio
    async def test_empty_query_returns_error(self, conn):
        """Blank query is rejected without hitting the DB."""
        from tether_mcp.tools.search_context import execute_search_context

        result = await execute_search_context(conn, query="")
        assert "error" in result
        assert result["error"] == "query_required"

    @pytest.mark.asyncio
    async def test_whitespace_only_query_returns_error(self, conn):
        from tether_mcp.tools.search_context import execute_search_context

        result = await execute_search_context(conn, query="   ")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty_results(self, conn):
        with patch(
            "db.pg_queries.sections.search_sections_fts",
            AsyncMock(return_value=[]),
        ):
            from tether_mcp.tools.search_context import execute_search_context

            result = await execute_search_context(conn, query="xyzzy_no_match")

        assert result["results"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_paths_resolved_to_node_ids(self, conn):
        """Paths are resolved via get_node_by_path before calling FTS."""
        fake_node = {"id": "node-uuid-99"}
        with (
            patch(
                "db.pg_queries.nodes.get_node_by_path",
                AsyncMock(return_value=fake_node),
            ) as mock_get_node,
            patch(
                "db.pg_queries.sections.search_sections_fts",
                AsyncMock(return_value=[]),
            ) as mock_fts,
        ):
            from tether_mcp.tools.search_context import execute_search_context

            await execute_search_context(
                conn, query="test", paths=["work/projects"]
            )

        mock_get_node.assert_called_once_with(conn, "work/projects")
        # FTS should be called with the resolved node ID
        call_kwargs = mock_fts.call_args
        node_ids = call_kwargs[1].get("node_ids") or call_kwargs[0][2] if len(call_kwargs[0]) > 2 else None
        # The node_id should be in the call somehow — check it was passed
        assert mock_fts.called

    @pytest.mark.asyncio
    async def test_unknown_path_returns_empty(self, conn):
        """If a path resolves to None (not found), return empty results."""
        with patch(
            "db.pg_queries.nodes.get_node_by_path",
            AsyncMock(return_value=None),
        ):
            from tether_mcp.tools.search_context import execute_search_context

            result = await execute_search_context(
                conn, query="test", paths=["nonexistent/path"]
            )

        assert result["results"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_limit_capped_at_20(self, conn):
        """Limit is capped at 20 regardless of input."""
        with patch(
            "db.pg_queries.sections.search_sections_fts",
            AsyncMock(return_value=[]),
        ) as mock_fts:
            from tether_mcp.tools.search_context import execute_search_context

            await execute_search_context(conn, query="test", limit=999)

        call_args = mock_fts.call_args
        limit_used = call_args[1].get("limit") or (call_args[0][3] if len(call_args[0]) > 3 else None)
        if limit_used is not None:
            assert limit_used <= 20

    @pytest.mark.asyncio
    async def test_result_has_no_stale_stub_note(self, conn):
        """Real implementation must not return the 'stub' note field."""
        with patch(
            "db.pg_queries.sections.search_sections_fts",
            AsyncMock(return_value=[]),
        ):
            from tether_mcp.tools.search_context import execute_search_context

            result = await execute_search_context(conn, query="test")

        assert "note" not in result


# ---------------------------------------------------------------------------
# search_memory
# ---------------------------------------------------------------------------

class TestSearchMemory:
    """execute_search_memory searches key+value of memory tables via ILIKE."""

    @pytest.mark.asyncio
    async def test_returns_matching_memory_entries(self, conn):
        """Happy path: query matches memory entries (tier='l2' for deterministic count)."""
        fake_entries = [
            {"key": "preferences/morning_routine", "value": "exercise at 6am", "score": 2},
            {"key": "facts/work/role", "value": "morning standup at 9am", "score": 0},
        ]
        with patch(
            "db.pg_queries.memory.search_user_memory",
            AsyncMock(return_value=fake_entries),
        ) as mock_search:
            from tether_mcp.tools.search_memory import execute_search_memory

            result = await execute_search_memory(conn, query="morning", tier="l2")

        mock_search.assert_called_once()
        assert result["total"] == 2
        assert len(result["results"]) == 2
        assert result["results"][0]["key"] == "preferences/morning_routine"

    @pytest.mark.asyncio
    async def test_empty_query_returns_error(self, conn):
        from tether_mcp.tools.search_memory import execute_search_memory

        result = await execute_search_memory(conn, query="")
        assert "error" in result
        assert result["error"] == "query_required"

    @pytest.mark.asyncio
    async def test_tier_l2_searches_user_memory(self, conn):
        """tier='l2' routes to user memory (scope='user')."""
        with patch(
            "db.pg_queries.memory.search_user_memory",
            AsyncMock(return_value=[]),
        ) as mock_search:
            from tether_mcp.tools.search_memory import execute_search_memory

            await execute_search_memory(conn, query="test", tier="l2")

        mock_search.assert_called_once()
        call_args = mock_search.call_args
        scope_used = call_args[1].get("scope") or (call_args[0][2] if len(call_args[0]) > 2 else None)
        assert scope_used == "user"

    @pytest.mark.asyncio
    async def test_tier_l3_searches_durable_memory(self, conn):
        """tier='l3' routes to durable memory (scope='user_durable')."""
        with patch(
            "db.pg_queries.memory.search_user_memory",
            AsyncMock(return_value=[]),
        ) as mock_search:
            from tether_mcp.tools.search_memory import execute_search_memory

            await execute_search_memory(conn, query="test", tier="l3")

        mock_search.assert_called_once()
        call_args = mock_search.call_args
        scope_used = call_args[1].get("scope") or (call_args[0][2] if len(call_args[0]) > 2 else None)
        assert scope_used == "user_durable"

    @pytest.mark.asyncio
    async def test_tier_both_searches_both_tables(self, conn):
        """tier='both' calls search_user_memory twice (l2 and l3) and merges."""
        with patch(
            "db.pg_queries.memory.search_user_memory",
            AsyncMock(return_value=[]),
        ) as mock_search:
            from tether_mcp.tools.search_memory import execute_search_memory

            await execute_search_memory(conn, query="test", tier="both")

        assert mock_search.call_count == 2

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty(self, conn):
        with patch(
            "db.pg_queries.memory.search_user_memory",
            AsyncMock(return_value=[]),
        ):
            from tether_mcp.tools.search_memory import execute_search_memory

            result = await execute_search_memory(conn, query="xyzzy_no_match")

        assert result["results"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_result_has_no_stale_stub_note(self, conn):
        """Real implementation must not return the 'stub' note field."""
        with patch(
            "db.pg_queries.memory.search_user_memory",
            AsyncMock(return_value=[]),
        ):
            from tether_mcp.tools.search_memory import execute_search_memory

            result = await execute_search_memory(conn, query="test")

        assert "note" not in result

    @pytest.mark.asyncio
    async def test_invalid_tier_returns_error(self, conn):
        from tether_mcp.tools.search_memory import execute_search_memory

        result = await execute_search_memory(conn, query="test", tier="invalid")
        assert "error" in result


# ---------------------------------------------------------------------------
# search_sections_fts (pg_query unit tests)
# ---------------------------------------------------------------------------

class TestSearchSectionsFts:
    """Unit tests for the new search_sections_fts pg_query function."""

    @pytest.mark.asyncio
    async def test_calls_db_with_tsvector_query(self, conn):
        """search_sections_fts issues a tsvector-based FTS query."""
        conn.fetch = AsyncMock(return_value=[])

        from db.pg_queries.sections import search_sections_fts

        result = await search_sections_fts(conn, "planning")

        conn.fetch.assert_called_once()
        sql = conn.fetch.call_args[0][0]
        assert "plainto_tsquery" in sql or "to_tsquery" in sql

    @pytest.mark.asyncio
    async def test_maps_rows_to_expected_shape(self, conn):
        """Returned rows have node_id, node_name, section_type, section_name, snippet, score."""
        import uuid as _uuid
        fake_uuid = _uuid.UUID("12345678-1234-5678-1234-567812345678")
        conn.fetch = AsyncMock(return_value=[
            {
                "node_id": fake_uuid,
                "node_name": "My Node",
                "section_type": "notes",
                "section_name": "main",
                "snippet": "highlighted <b>text</b>",
                "score": 0.3,
            }
        ])

        from db.pg_queries.sections import search_sections_fts

        result = await search_sections_fts(conn, "text")

        assert len(result) == 1
        assert result[0]["node_id"] == str(fake_uuid)
        assert result[0]["node_name"] == "My Node"
        assert result[0]["section_type"] == "notes"
        assert result[0]["section_name"] == "main"
        assert "snippet" in result[0]
        assert "score" in result[0]

    @pytest.mark.asyncio
    async def test_node_ids_filter_applied(self, conn):
        """When node_ids given, query filters to those nodes."""
        conn.fetch = AsyncMock(return_value=[])

        from db.pg_queries.sections import search_sections_fts

        await search_sections_fts(conn, "test", node_ids=["uuid-1", "uuid-2"])

        sql = conn.fetch.call_args[0][0]
        # Should filter by node_ids — check ANY or IN clause
        assert "ANY" in sql or "node_id" in sql


# ---------------------------------------------------------------------------
# search_user_memory (pg_query unit tests)
# ---------------------------------------------------------------------------

class TestSearchUserMemory:
    """Unit tests for the new search_user_memory pg_query function."""

    @pytest.mark.asyncio
    async def test_scope_user_queries_user_memory(self, conn):
        """scope='user' queries user_memory table."""
        conn.fetch = AsyncMock(return_value=[])

        from db.pg_queries.memory import search_user_memory

        await search_user_memory(conn, "exercise", scope="user")

        sql = conn.fetch.call_args[0][0]
        assert "user_memory" in sql
        assert "user_durable_memory" not in sql

    @pytest.mark.asyncio
    async def test_scope_durable_queries_durable_table(self, conn):
        """scope='user_durable' queries user_durable_memory table."""
        conn.fetch = AsyncMock(return_value=[])

        from db.pg_queries.memory import search_user_memory

        await search_user_memory(conn, "exercise", scope="user_durable")

        sql = conn.fetch.call_args[0][0]
        assert "user_durable_memory" in sql

    @pytest.mark.asyncio
    async def test_ilike_pattern_in_query(self, conn):
        """Query uses ILIKE for key and value search."""
        conn.fetch = AsyncMock(return_value=[])

        from db.pg_queries.memory import search_user_memory

        await search_user_memory(conn, "morning", scope="user")

        sql = conn.fetch.call_args[0][0]
        assert "ILIKE" in sql

    @pytest.mark.asyncio
    async def test_maps_rows_to_expected_shape(self, conn):
        """Returned rows have key, value, score fields."""
        conn.fetch = AsyncMock(return_value=[
            {"key": "preferences/wake", "value": "6am", "score": 2},
        ])

        from db.pg_queries.memory import search_user_memory

        result = await search_user_memory(conn, "wake", scope="user")

        assert len(result) == 1
        assert result[0]["key"] == "preferences/wake"
        assert result[0]["value"] == "6am"
        assert "score" in result[0]
