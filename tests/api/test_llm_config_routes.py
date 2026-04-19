"""Tests for /api/llm-config endpoints."""
import yaml
import pytest
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport

from api.auth import create_jwt
from tests.api.conftest import TEST_USER_ID, TEST_USERNAME
import api.routes.llm_config as llm_config_module


@pytest.fixture
async def llm_client(tmp_path, monkeypatch):
    """AsyncClient with a patched _CONFIG_PATH so config writes go to tmp_path."""
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(llm_config_module, "_CONFIG_PATH", config_path)

    from api.main import create_app
    from db.pool_middleware import get_db_conn

    app = create_app()
    # ASGITransport does not trigger lifespan — set state directly.
    app.state.pool = None

    # llm-config routes don't use get_db_conn, but override anyway to prevent errors
    async def override_get_db_conn():
        yield None  # type: ignore[misc]

    app.dependency_overrides[get_db_conn] = override_get_db_conn

    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"tether_token": token},
    ) as client:
        yield client, config_path


@pytest.mark.asyncio
async def test_get_returns_defaults_when_no_config(llm_client):
    client, _ = llm_client
    resp = await client.get("/api/llm-config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["models"]["orchestrator"] == "claude-sonnet-4-6"
    assert data["llm"]["thinking_enabled"] is True
    assert "model_roles" in data


@pytest.mark.asyncio
async def test_get_returns_model_roles_list(llm_client):
    client, _ = llm_client
    resp = await client.get("/api/llm-config")
    roles = resp.json()["model_roles"]
    assert "orchestrator" in roles
    assert "meta_eval" in roles
    assert "quick_classifier" in roles


@pytest.mark.asyncio
async def test_put_updates_model_assignment(llm_client):
    client, _ = llm_client
    resp = await client.put("/api/llm-config", json={
        "models": {"orchestrator": "claude-haiku-4-5-20251001"},
    })
    assert resp.status_code == 200
    get_resp = await client.get("/api/llm-config")
    assert get_resp.json()["models"]["orchestrator"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_put_updates_llm_settings(llm_client):
    client, _ = llm_client
    resp = await client.put("/api/llm-config", json={
        "llm": {"thinking_budget": 16000, "beacon_score_threshold": 12},
    })
    assert resp.status_code == 200
    get_resp = await client.get("/api/llm-config")
    data = get_resp.json()
    assert data["llm"]["thinking_budget"] == 16000
    assert data["llm"]["beacon_score_threshold"] == 12


@pytest.mark.asyncio
async def test_partial_update_preserves_other_fields(llm_client):
    client, _ = llm_client
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
async def test_put_writes_yaml_to_disk(llm_client):
    client, config_path = llm_client
    await client.put("/api/llm-config", json={
        "models": {"orchestrator": "my-model"},
    })
    assert config_path.exists()
    content = yaml.safe_load(config_path.read_text())
    assert content["models"]["orchestrator"] == "my-model"
