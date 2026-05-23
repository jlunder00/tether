"""Unit test for get_most_recent_telegram_user SQL correctness.

Wave 6 / Bug 2: the query used `ORDER BY tc.created_at` but the
telegram_connections table has no created_at column (only user_id and
telegram_chat_id). Postgres errors: "column tc.created_at does not exist".

Fix: order by u.created_at (users table, which does have the column).

This test does not require a live DATABASE_URL — it mocks conn.fetchrow
and captures the SQL string to verify the column reference is correct.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock


class TestGetMostRecentTelegramUserQuery:
    @pytest.mark.asyncio
    async def test_query_does_not_reference_tc_created_at(self):
        """The SQL must NOT reference tc.created_at (column doesn't exist on telegram_connections)."""
        captured_sql: list[str] = []

        mock_conn = AsyncMock()
        async def _capture_fetchrow(sql, *args, **kwargs):
            captured_sql.append(sql)
            return None
        mock_conn.fetchrow = _capture_fetchrow

        from db.pg_auth_queries import get_most_recent_telegram_user
        await get_most_recent_telegram_user(mock_conn)

        assert captured_sql, "fetchrow was never called"
        sql = captured_sql[0]
        assert "tc.created_at" not in sql, (
            f"Query must not reference tc.created_at (column doesn't exist on telegram_connections). "
            f"Full SQL:\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_query_orders_by_u_created_at(self):
        """The SQL must order by u.created_at (users table has this column)."""
        captured_sql: list[str] = []

        mock_conn = AsyncMock()
        async def _capture_fetchrow(sql, *args, **kwargs):
            captured_sql.append(sql)
            return None
        mock_conn.fetchrow = _capture_fetchrow

        from db.pg_auth_queries import get_most_recent_telegram_user
        await get_most_recent_telegram_user(mock_conn)

        assert captured_sql, "fetchrow was never called"
        sql = captured_sql[0]
        assert "u.created_at" in sql, (
            f"Query must order by u.created_at. Full SQL:\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_returns_none_when_no_row(self):
        """Returns None when fetchrow returns no match."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        from db.pg_auth_queries import get_most_recent_telegram_user
        result = await get_most_recent_telegram_user(mock_conn)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_dict_when_row_found(self):
        """Returns dict with id and telegram_chat_id when a user row is found."""
        import uuid
        fake_id = uuid.UUID("00000000-0000-0000-0000-000000000042")
        mock_row = {"id": fake_id, "telegram_chat_id": "chat-999"}

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)

        from db.pg_auth_queries import get_most_recent_telegram_user
        result = await get_most_recent_telegram_user(mock_conn)

        assert result is not None
        assert result["id"] == "00000000-0000-0000-0000-000000000042"
        assert result["telegram_chat_id"] == "chat-999"
