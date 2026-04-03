"""Tests for /api/llm-config endpoints."""
import yaml
import pytest
from pathlib import Path
from db.schema import init_db
from api.main import create_app
from tests.api.conftest import make_authenticated_client
import api.routes.llm_config as llm_config_module


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "tether.db"
    init_db(path)
    return path


@pytest.fixture
def app(db_path, tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(llm_config_module, "_CONFIG_PATH", config_path)
    return create_app(db_path=db_path)


@pytest.mark.asyncio
async def test_get_returns_defaults_when_no_config(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/llm-config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["models"]["orchestrator"] == "claude-sonnet-4-6"
    assert data["llm"]["thinking_enabled"] is True
    assert "model_roles" in data


@pytest.mark.asyncio
async def test_get_returns_model_roles_list(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.get("/api/llm-config")
    roles = resp.json()["model_roles"]
    assert "orchestrator" in roles
    assert "meta_eval" in roles
    assert "quick_classifier" in roles


@pytest.mark.asyncio
async def test_put_updates_model_assignment(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.put("/api/llm-config", json={
            "models": {"orchestrator": "claude-haiku-4-5-20251001"},
        })
        assert resp.status_code == 200
        get_resp = await client.get("/api/llm-config")
    assert get_resp.json()["models"]["orchestrator"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_put_updates_llm_settings(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        resp = await client.put("/api/llm-config", json={
            "llm": {"thinking_budget": 16000, "beacon_score_threshold": 12},
        })
        assert resp.status_code == 200
        get_resp = await client.get("/api/llm-config")
    data = get_resp.json()
    assert data["llm"]["thinking_budget"] == 16000
    assert data["llm"]["beacon_score_threshold"] == 12


@pytest.mark.asyncio
async def test_partial_update_preserves_other_fields(app, db_path):
    async with make_authenticated_client(app, db_path) as client:
        await client.put("/api/llm-config", json={
            "models": {"orchestrator": "custom-model"},
            "llm": {"thinking_budget": 4000},
        })
        await client.put("/api/llm-config", json={
            "llm": {"beacon_cooldown_minutes": 60},
        })
        get_resp = await client.get("/api/llm-config")
    data = get_resp.json()
    assert data["llm"]["thinking_budget"] == 4000
    assert data["llm"]["beacon_cooldown_minutes"] == 60


@pytest.mark.asyncio
async def test_put_writes_yaml_to_disk(app, db_path, tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(llm_config_module, "_CONFIG_PATH", config_path)
    async with make_authenticated_client(app, db_path) as client:
        await client.put("/api/llm-config", json={
            "models": {"orchestrator": "my-model"},
        })
    assert config_path.exists()
    content = yaml.safe_load(config_path.read_text())
    assert content["models"]["orchestrator"] == "my-model"
