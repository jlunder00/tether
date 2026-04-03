import pytest
from db.schema import init_db
from db.queries import upsert_context_entry
from api.main import create_app
from tests.api.conftest import make_authenticated_client


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    upsert_context_entry(path, "Job Applications", "ML engineer roles. Priority 1.")
    upsert_context_entry(path, "5D Multiverse", "Game engine. Flex time only.")
    upsert_context_entry(path, "Intellipat", "Patent startup.")
    upsert_context_entry(path, "Intellipat/Backend", "Backend services.")
    upsert_context_entry(path, "Intellipat/Frontend", "React frontend.")
    return path


@pytest.fixture
def app(db_path):
    return create_app(db_path=db_path)


@pytest.mark.asyncio
async def test_get_context_entries(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/context")
    assert resp.status_code == 200
    subjects = [e["subject"] for e in resp.json()]
    assert "Job Applications" in subjects


@pytest.mark.asyncio
async def test_put_context_entry(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
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
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.delete("/api/context/5D%20Multiverse")
    assert resp.status_code == 200
    from db.queries import get_context_entries
    subjects = [e["subject"] for e in get_context_entries(db_path)]
    assert "5D Multiverse" not in subjects


@pytest.mark.asyncio
async def test_get_context_top_level_only(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/context?top_level_only=true")
    assert resp.status_code == 200
    subjects = {e["subject"] for e in resp.json()}
    assert "Intellipat/Backend" not in subjects
    assert "Intellipat" in subjects


@pytest.mark.asyncio
async def test_get_context_prefix(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/context?prefix=Intellipat")
    assert resp.status_code == 200
    subjects = {e["subject"] for e in resp.json()}
    assert subjects == {"Intellipat", "Intellipat/Backend", "Intellipat/Frontend"}


@pytest.mark.asyncio
async def test_get_single_context_entry(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/context/Job%20Applications")
    assert resp.status_code == 200
    assert resp.json()["subject"] == "Job Applications"


@pytest.mark.asyncio
async def test_get_single_context_entry_with_slash(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/context/Intellipat/Backend")
    assert resp.status_code == 200
    assert resp.json()["subject"] == "Intellipat/Backend"


@pytest.mark.asyncio
async def test_get_single_context_entry_not_found(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/context/Nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_context_entry(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.post("/api/context/Intellipat/rename",
                                 json={"new_subject": "IntelliPat"})
    assert resp.status_code == 200
    from db.queries import get_context_entries
    subjects = {e["subject"] for e in get_context_entries(db_path)}
    assert "Intellipat" not in subjects
    assert {"IntelliPat", "IntelliPat/Backend", "IntelliPat/Frontend"} <= subjects


@pytest.mark.asyncio
async def test_delete_cascades_to_children(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.delete("/api/context/Intellipat")
    assert resp.status_code == 200
    from db.queries import get_context_entries
    subjects = {e["subject"] for e in get_context_entries(db_path)}
    assert "Intellipat" not in subjects
    assert "Intellipat/Backend" not in subjects
    assert "Intellipat/Frontend" not in subjects
