"""Tests for db/pg_queries/sections.py — upsert, FTS search."""
import pytest

from tests.db.pg_conftest import conn  # noqa: F401
from db.pg_queries.nodes import create_node
from db.pg_queries.sections import (
    upsert_section, get_section, get_sections, append_section,
    delete_section, list_section_files, create_section_file,
    rename_section_file, reorder_section_files, search_sections,
)


@pytest.fixture
async def node_id(conn):
    node = await create_node(conn, name="SectionTestNode", node_type="context")
    return node["id"]


@pytest.mark.asyncio
async def test_upsert_and_get_section(conn, node_id):
    await upsert_section(conn, node_id, "notes", "Hello world")
    section = await get_section(conn, node_id, "notes")
    assert section is not None
    assert section["body"] == "Hello world"


@pytest.mark.asyncio
async def test_upsert_increments_version(conn, node_id):
    await upsert_section(conn, node_id, "notes", "v1")
    await upsert_section(conn, node_id, "notes", "v2")
    section = await get_section(conn, node_id, "notes")
    assert section["body"] == "v2"
    assert section["version"] >= 1


@pytest.mark.asyncio
async def test_append_section(conn, node_id):
    await upsert_section(conn, node_id, "log", "Line 1")
    await append_section(conn, node_id, "log", "Line 2")
    section = await get_section(conn, node_id, "log")
    assert "Line 1" in section["body"]
    assert "Line 2" in section["body"]


@pytest.mark.asyncio
async def test_section_files(conn, node_id):
    await create_section_file(conn, node_id, "docs", "readme", "# Readme content")
    await create_section_file(conn, node_id, "docs", "changelog", "## Changes")
    files = await list_section_files(conn, node_id, "docs")
    names = [f["name"] for f in files]
    assert "readme" in names
    assert "changelog" in names


@pytest.mark.asyncio
async def test_rename_section_file(conn, node_id):
    await create_section_file(conn, node_id, "docs", "old_name", "body")
    await rename_section_file(conn, node_id, "docs", "old_name", "new_name")
    section = await get_section(conn, node_id, "docs", "new_name")
    assert section is not None
    assert section["body"] == "body"


@pytest.mark.asyncio
async def test_reorder_section_files(conn, node_id):
    await create_section_file(conn, node_id, "docs", "alpha", "")
    await create_section_file(conn, node_id, "docs", "beta", "")
    await reorder_section_files(conn, node_id, "docs", ["beta", "alpha"])
    files = await list_section_files(conn, node_id, "docs")
    names = [f["name"] for f in files]
    assert names.index("beta") < names.index("alpha")


@pytest.mark.asyncio
async def test_fts_search(conn, node_id):
    await upsert_section(conn, node_id, "notes", "The quick brown fox jumps over the lazy dog")
    results = await search_sections(conn, "quick fox")
    assert any(r["node_id"] == node_id for r in results)
    # Snippet should contain highlighted terms
    hit = next(r for r in results if r["node_id"] == node_id)
    assert "snippet" in hit


@pytest.mark.asyncio
async def test_delete_section(conn, node_id):
    await upsert_section(conn, node_id, "temp", "delete me")
    await delete_section(conn, node_id, "temp")
    section = await get_section(conn, node_id, "temp")
    assert section is None
