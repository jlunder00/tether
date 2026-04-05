import pytest
import asyncio


class TestSessionDoneTool:
    def test_session_done_returns_acknowledgement(self):
        from tether_mcp.server import session_done
        result = asyncio.run(session_done(summary="Organized 15 tasks across 5 anchors."))
        assert "acknowledged" in result.lower()
        assert "Organized 15 tasks" in result

    def test_session_done_handles_empty_summary(self):
        from tether_mcp.server import session_done
        result = asyncio.run(session_done())
        assert "acknowledged" in result.lower()
        assert "none provided" in result.lower()
