"""Tests for client_timezone support in get_anchors and get_plan.

TDD — these tests are written against the NEW interface before implementation.
All tests should fail until server.py is updated to:
  - accept client_timezone: str = "" on get_anchors and get_plan
  - return timezone_used and is_current fields in get_anchors
  - use client local "today" in get_plan when no date is given
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SAMPLE_ANCHORS = [
    {"anchor_id": "1", "name": "Morning", "time": "06:00"},
    {"anchor_id": "2", "name": "Work", "time": "09:00"},
    {"anchor_id": "3", "name": "Evening", "time": "18:00"},
]


# ---------------------------------------------------------------------------
# Helper: build the full DB mock stack for get_anchors / get_plan
# ---------------------------------------------------------------------------

def _db_mocks(return_anchors=SAMPLE_ANCHORS):
    """Return (mock_pool, mock_conn, mock_pg, mock_db_anchors) ready to patch."""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pg = MagicMock()
    mock_db_anchors = AsyncMock(return_value=return_anchors)
    # pg.get_conn returns an async context manager yielding mock_conn
    mock_pg.get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pg.get_conn.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool, mock_conn, mock_pg, mock_db_anchors


# ---------------------------------------------------------------------------
# Unit tests: _current_anchor helper with aware datetimes
# ---------------------------------------------------------------------------


class TestCurrentAnchorHelper:
    """_current_anchor must not raise TypeError when given an aware datetime."""

    def test_naive_now_selects_work_at_1430(self):
        """Baseline: naive 14:30 → Work anchor (between 09:00 and 18:00)."""
        from tether_mcp.server import _current_anchor

        now = datetime(2026, 6, 15, 14, 30)
        assert _current_anchor(SAMPLE_ANCHORS, now=now)["name"] == "Work"

    def test_aware_now_does_not_raise_type_error(self):
        """Passing an aware datetime must not raise TypeError."""
        from zoneinfo import ZoneInfo
        from tether_mcp.server import _current_anchor

        la = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 6, 15, 10, 0, tzinfo=la)
        # Should not raise; the result is any valid anchor dict
        result = _current_anchor(SAMPLE_ANCHORS, now=now)
        assert result is not None

    def test_aware_now_morning_before_work(self):
        """07:30 LA → Morning (before Work at 09:00 LA)."""
        from zoneinfo import ZoneInfo
        from tether_mcp.server import _current_anchor

        la = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 6, 15, 7, 30, tzinfo=la)
        assert _current_anchor(SAMPLE_ANCHORS, now=now)["name"] == "Morning"

    def test_aware_now_evening_after_1800(self):
        """19:00 LA → Evening (after 18:00 LA)."""
        from zoneinfo import ZoneInfo
        from tether_mcp.server import _current_anchor

        la = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 6, 15, 19, 0, tzinfo=la)
        assert _current_anchor(SAMPLE_ANCHORS, now=now)["name"] == "Evening"


# ---------------------------------------------------------------------------
# Integration tests: get_anchors MCP tool
# ---------------------------------------------------------------------------


class TestGetAnchorsTool:

    @pytest.mark.asyncio
    async def test_no_timezone_returns_timezone_used_utc(self):
        """Without client_timezone, response includes timezone_used='UTC'."""
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, mock_db_anchors = _db_mocks()
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_anchors", new=mock_db_anchors):
            result = await mcp_server.get_anchors()

        assert result["timezone_used"] == "UTC"

    @pytest.mark.asyncio
    async def test_valid_timezone_echoed_in_response(self):
        """client_timezone is echoed back in timezone_used."""
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, mock_db_anchors = _db_mocks()
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_anchors", new=mock_db_anchors):
            result = await mcp_server.get_anchors(client_timezone="America/Los_Angeles")

        assert result["timezone_used"] == "America/Los_Angeles"

    @pytest.mark.asyncio
    async def test_invalid_timezone_falls_back_to_utc_no_raise(self):
        """Invalid IANA string must not raise — falls back to UTC."""
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, mock_db_anchors = _db_mocks()
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_anchors", new=mock_db_anchors):
            result = await mcp_server.get_anchors(client_timezone="Not/A/Zone")

        assert result["timezone_used"] == "UTC"
        assert "anchors" in result
        assert "current" in result

    @pytest.mark.asyncio
    async def test_each_anchor_has_is_current_field(self):
        """Every anchor dict in the response list must have an is_current field."""
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, mock_db_anchors = _db_mocks()
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_anchors", new=mock_db_anchors):
            result = await mcp_server.get_anchors(client_timezone="America/New_York")

        for anchor in result["anchors"]:
            assert "is_current" in anchor, f"Anchor {anchor!r} missing is_current"

    @pytest.mark.asyncio
    async def test_exactly_one_anchor_is_current(self):
        """Exactly one anchor should have is_current=True."""
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, mock_db_anchors = _db_mocks()
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_anchors", new=mock_db_anchors):
            result = await mcp_server.get_anchors(client_timezone="America/Chicago")

        current_list = [a for a in result["anchors"] if a["is_current"]]
        assert len(current_list) == 1

    @pytest.mark.asyncio
    async def test_current_anchor_matches_is_current_anchor(self):
        """top-level current field must match the anchor marked is_current=True."""
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, mock_db_anchors = _db_mocks()
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_anchors", new=mock_db_anchors):
            result = await mcp_server.get_anchors(client_timezone="America/Denver")

        current = result["current"]
        # Find the anchor marked is_current
        marked = next((a for a in result["anchors"] if a["is_current"]), None)
        assert marked is not None
        assert marked["anchor_id"] == current["anchor_id"]

    @pytest.mark.asyncio
    async def test_empty_anchors_list_no_crash(self):
        """Empty anchor list → current=None, anchors=[], no exception."""
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, mock_db_anchors = _db_mocks(return_anchors=[])
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_anchors", new=mock_db_anchors):
            result = await mcp_server.get_anchors(client_timezone="America/Chicago")

        assert result["current"] is None
        assert result["anchors"] == []

    @pytest.mark.asyncio
    async def test_la_timezone_discriminates_from_utc(self):
        """A time that's morning in LA but afternoon in UTC picks different anchors.

        UTC 14:00 → Work active (09:00–18:00 UTC).
        LA 07:00 (= UTC 14:00 in summer PDT) → Morning active (06:00–09:00 LA).
        """
        from zoneinfo import ZoneInfo
        from tether_mcp import server as mcp_server

        # UTC 14:00: Work active in UTC, Morning active in LA (07:00 PDT)
        fixed_utc = datetime(2026, 6, 15, 14, 0)  # naive, treated as UTC

        mock_pool, mock_conn, mock_pg, _ = _db_mocks()

        # --- UTC case (no client_timezone) ---
        mock_db_anchors_utc = AsyncMock(return_value=SAMPLE_ANCHORS)
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_anchors", new=mock_db_anchors_utc), \
             patch("tether_mcp.server.datetime") as mock_dt:
            # Preserve the datetime constructor so _current_anchor can still build
            # datetime(y, m, d, h, min) objects; only intercept datetime.now().
            mock_dt.side_effect = datetime
            mock_dt.now.side_effect = lambda tz=None: (
                datetime(2026, 6, 15, 14, 0, tzinfo=tz) if tz else fixed_utc
            )
            result_utc = await mcp_server.get_anchors()

        # --- LA case ---
        mock_db_anchors_la = AsyncMock(return_value=SAMPLE_ANCHORS)
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_anchors", new=mock_db_anchors_la), \
             patch("tether_mcp.server.datetime") as mock_dt:
            la = ZoneInfo("America/Los_Angeles")
            mock_dt.side_effect = datetime
            mock_dt.now.side_effect = lambda tz=None: (
                datetime(2026, 6, 15, 7, 0, tzinfo=la) if tz else fixed_utc
            )
            result_la = await mcp_server.get_anchors(client_timezone="America/Los_Angeles")

        # UTC sees Work, LA sees Morning
        assert result_utc["current"]["name"] == "Work"
        assert result_la["current"]["name"] == "Morning"


# ---------------------------------------------------------------------------
# Integration tests: get_plan MCP tool
# ---------------------------------------------------------------------------


class TestGetPlanTimezone:

    @pytest.mark.asyncio
    async def test_explicit_date_bypasses_timezone(self):
        """When date= is given explicitly, client_timezone doesn't change it."""
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, _ = _db_mocks()
        mock_get_plan = AsyncMock(return_value={"date": "2026-06-01", "anchors": []})
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_plan", new=mock_get_plan):
            await mcp_server.get_plan(date="2026-06-01", client_timezone="America/Los_Angeles")

        mock_get_plan.assert_called_once()
        called_date = mock_get_plan.call_args[0][1]
        assert called_date == "2026-06-01"

    @pytest.mark.asyncio
    async def test_no_date_with_timezone_uses_local_today(self):
        """When no date given, client_timezone determines which 'today' to use."""
        from zoneinfo import ZoneInfo
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, _ = _db_mocks()
        mock_get_plan = AsyncMock(return_value={"date": "2026-06-15", "anchors": []})

        la = ZoneInfo("America/Los_Angeles")
        # LA date: 2026-06-15; UTC date (next day): 2026-06-16
        # Use a fixed "now" that's just past midnight UTC on June 16 = still June 15 in LA
        fixed_utc_midnight_plus = datetime(2026, 6, 16, 2, 0)  # 02:00 UTC = 19:00 PDT June 15

        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_plan", new=mock_get_plan), \
             patch("tether_mcp.server.datetime") as mock_dt:
            mock_dt.side_effect = datetime
            mock_dt.now.side_effect = lambda tz=None: (
                datetime(2026, 6, 15, 19, 0, tzinfo=la) if tz else fixed_utc_midnight_plus
            )
            await mcp_server.get_plan(client_timezone="America/Los_Angeles")

        called_date = mock_get_plan.call_args[0][1]
        # LA sees June 15, not June 16
        assert called_date == "2026-06-15"

    @pytest.mark.asyncio
    async def test_no_date_no_timezone_uses_server_today(self):
        """Without client_timezone, get_plan still works with server's local date."""
        from tether_mcp import server as mcp_server

        mock_pool, mock_conn, mock_pg, _ = _db_mocks()
        mock_get_plan = AsyncMock(return_value={"anchors": []})
        with patch.object(mcp_server, "_get_pool", new=AsyncMock(return_value=mock_pool)), \
             patch("tether_mcp.server.get_user_id", return_value=1), \
             patch("tether_mcp.server.pg", new=mock_pg), \
             patch("db.pg_queries.get_plan", new=mock_get_plan):
            await mcp_server.get_plan()

        mock_get_plan.assert_called_once()
        called_date = mock_get_plan.call_args[0][1]
        # Should be a valid ISO date string
        from datetime import date
        date.fromisoformat(called_date)  # raises ValueError if invalid
