import pytest
from pathlib import Path
try:
    from db.schema import init_db
    from db.queries import (
        create_session, get_active_session, update_session_state,
        update_session_activity, close_session, get_stale_sessions, get_db,
    )
except ImportError:
    pytestmark = pytest.mark.skip(reason="Skipping as Sqlite DB is deprecated and the required imports have been removed. Ensure Postgres equivalents are tested prior to removing these tests")


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "test.db"
    init_db(p)
    return p


class TestSessionQueries:
    def test_create_session(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        assert sid is not None
        session = get_active_session(db, chat_id="123")
        assert session is not None
        assert session["state"] == "active"
        assert session["turn_count"] == 0
        assert session["max_turns"] == 10

    def test_no_active_session_returns_none(self, db):
        assert get_active_session(db, chat_id="123") is None

    def test_update_session_state(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        update_session_state(db, sid, "waiting_user")
        session = get_active_session(db, chat_id="123")
        assert session["state"] == "waiting_user"

    def test_update_session_activity(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        update_session_activity(db, sid, turn_count=3)
        session = get_active_session(db, chat_id="123")
        assert session["turn_count"] == 3

    def test_close_session(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        close_session(db, sid, summary="Done organizing tasks")
        assert get_active_session(db, chat_id="123") is None

    def test_get_stale_sessions(self, db):
        sid = create_session(db, chat_id="123", max_turns=10)
        with get_db(db) as conn:
            conn.execute(
                "UPDATE sessions SET last_activity = datetime('now', '-20 minutes') WHERE id = ?",
                (sid,),
            )
        stale = get_stale_sessions(db, timeout_minutes=15)
        assert len(stale) == 1
        assert stale[0]["id"] == sid

    def test_only_one_active_session_per_chat(self, db):
        sid1 = create_session(db, chat_id="123", max_turns=10)
        sid2 = create_session(db, chat_id="123", max_turns=10)
        # Second session should be the active one
        session = get_active_session(db, chat_id="123")
        assert session["id"] == sid2
        # First session should be closed
        with get_db(db) as conn:
            row = conn.execute("SELECT state FROM sessions WHERE id = ?", (sid1,)).fetchone()
        assert row["state"] == "closed"
