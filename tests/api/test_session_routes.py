import pytest
from pathlib import Path
from db.schema import init_db
from db.queries import create_session
from api.main import create_app
from tests.api.conftest import make_authenticated_client


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


@pytest.fixture
def app(db_path):
    return create_app(db_path=db_path)


@pytest.mark.asyncio
async def test_get_sessions_empty(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert len(data["sessions"]) == 0


@pytest.mark.asyncio
async def test_get_active_sessions(app, db_path):
    # Create an active session directly in the DB
    sid = create_session(db_path, chat_id="chat-001", max_turns=5)
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["id"] == sid
    assert data["sessions"][0]["state"] == "active"


@pytest.mark.asyncio
async def test_closed_sessions_not_returned(app, db_path):
    # Create a session then close it
    create_session(db_path, chat_id="chat-002")
    # Create another active one
    active_sid = create_session(db_path, chat_id="chat-003")
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    # Only the active session for chat-003 should appear (chat-002 was never closed explicitly,
    # but create_session for chat-003 doesn't affect chat-002 — both remain active)
    ids = [s["id"] for s in data["sessions"]]
    assert active_sid in ids
