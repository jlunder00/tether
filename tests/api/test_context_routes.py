import pytest
from httpx import AsyncClient, ASGITransport
from db.schema import init_db
from db.queries import upsert_context_entry
from api.main import create_app


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_context_entry(path, "Job Applications", "ML engineer roles. Priority 1.")
    upsert_context_entry(path, "5D Multiverse", "Game engine. Flex time only.")
    return path


@pytest.fixture
def app(db_path):
    return create_app(db_path=db_path)


@pytest.mark.asyncio
async def test_get_context_entries(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/context")
    assert resp.status_code == 200
    subjects = [e["subject"] for e in resp.json()]
    assert "Job Applications" in subjects


@pytest.mark.asyncio
async def test_put_context_entry(app, db_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/api/context/Job%20Applications",
            json={"body": "Updated body."}
        )
    assert resp.status_code == 200
    from db.queries import get_context_entries
    entries = get_context_entries(db_path)
    match = next(e for e in entries if e["subject"] == "Job Applications")
    assert match["body"] == "Updated body."


@pytest.mark.asyncio
async def test_delete_context_entry(app, db_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/context/5D%20Multiverse")
    assert resp.status_code == 200
    from db.queries import get_context_entries
    subjects = [e["subject"] for e in get_context_entries(db_path)]
    assert "5D Multiverse" not in subjects
