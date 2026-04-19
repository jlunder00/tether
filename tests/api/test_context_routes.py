import pytest
from db.pg_queries import upsert_context_entry, get_context_entries


@pytest.mark.asyncio
async def test_get_context_entries(api_client, conn):
    await upsert_context_entry(conn, "Job Applications", "ML engineer roles. Priority 1.")
    await upsert_context_entry(conn, "5D Multiverse", "Game engine. Flex time only.")
    resp = await api_client.get("/api/context")
    assert resp.status_code == 200
    subjects = [e["subject"] for e in resp.json()]
    assert "Job Applications" in subjects


@pytest.mark.asyncio
async def test_put_context_entry(api_client, conn):
    await upsert_context_entry(conn, "Job Applications", "ML engineer roles. Priority 1.")
    resp = await api_client.put(
        "/api/context/Job%20Applications",
        json={"body": "Updated body."}
    )
    assert resp.status_code == 200
    entries = await get_context_entries(conn)
    match = next(e for e in entries if e["subject"] == "Job Applications")
    assert match["body"] == "Updated body."


@pytest.mark.asyncio
async def test_delete_context_entry(api_client, conn):
    await upsert_context_entry(conn, "5D Multiverse", "Game engine. Flex time only.")
    resp = await api_client.delete("/api/context/5D%20Multiverse")
    assert resp.status_code == 200
    subjects = [e["subject"] for e in await get_context_entries(conn)]
    assert "5D Multiverse" not in subjects


@pytest.mark.asyncio
async def test_get_context_top_level_only(api_client, conn):
    await upsert_context_entry(conn, "Intellipat", "Patent startup.")
    await upsert_context_entry(conn, "Intellipat/Backend", "Backend services.")
    await upsert_context_entry(conn, "Intellipat/Frontend", "React frontend.")
    resp = await api_client.get("/api/context?top_level_only=true")
    assert resp.status_code == 200
    subjects = {e["subject"] for e in resp.json()}
    assert "Intellipat/Backend" not in subjects
    assert "Intellipat" in subjects


@pytest.mark.asyncio
async def test_get_context_prefix(api_client, conn):
    await upsert_context_entry(conn, "Intellipat", "Patent startup.")
    await upsert_context_entry(conn, "Intellipat/Backend", "Backend services.")
    await upsert_context_entry(conn, "Intellipat/Frontend", "React frontend.")
    resp = await api_client.get("/api/context?prefix=Intellipat")
    assert resp.status_code == 200
    subjects = {e["subject"] for e in resp.json()}
    assert subjects == {"Intellipat", "Intellipat/Backend", "Intellipat/Frontend"}


@pytest.mark.asyncio
async def test_get_single_context_entry(api_client, conn):
    await upsert_context_entry(conn, "Job Applications", "ML engineer roles.")
    resp = await api_client.get("/api/context/Job%20Applications")
    assert resp.status_code == 200
    assert resp.json()["subject"] == "Job Applications"


@pytest.mark.asyncio
async def test_get_single_context_entry_with_slash(api_client, conn):
    await upsert_context_entry(conn, "Intellipat", "Patent startup.")
    await upsert_context_entry(conn, "Intellipat/Backend", "Backend services.")
    resp = await api_client.get("/api/context/Intellipat/Backend")
    assert resp.status_code == 200
    assert resp.json()["subject"] == "Intellipat/Backend"


@pytest.mark.asyncio
async def test_get_single_context_entry_not_found(api_client, conn):
    resp = await api_client.get("/api/context/Nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_context_entry(api_client, conn):
    await upsert_context_entry(conn, "Intellipat", "Patent startup.")
    await upsert_context_entry(conn, "Intellipat/Backend", "Backend services.")
    await upsert_context_entry(conn, "Intellipat/Frontend", "React frontend.")
    resp = await api_client.post("/api/context/Intellipat/rename",
                                 json={"new_subject": "IntelliPat"})
    assert resp.status_code == 200
    subjects = {e["subject"] for e in await get_context_entries(conn)}
    assert "Intellipat" not in subjects
    assert {"IntelliPat", "IntelliPat/Backend", "IntelliPat/Frontend"} <= subjects


@pytest.mark.asyncio
async def test_delete_cascades_to_children(api_client, conn):
    await upsert_context_entry(conn, "Intellipat", "Patent startup.")
    await upsert_context_entry(conn, "Intellipat/Backend", "Backend services.")
    await upsert_context_entry(conn, "Intellipat/Frontend", "React frontend.")
    resp = await api_client.delete("/api/context/Intellipat")
    assert resp.status_code == 200
    subjects = {e["subject"] for e in await get_context_entries(conn)}
    assert "Intellipat" not in subjects
    assert "Intellipat/Backend" not in subjects
    assert "Intellipat/Frontend" not in subjects
