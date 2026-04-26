"""Unit tests for config/loader.py — TDD, no DB required."""
from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))


def _make_loader(baked_in_dir: Path, config_dir: Path | None = None):
    """Import TetherConfig fresh for each test instance."""
    from config.loader import TetherConfig
    return TetherConfig(baked_in_dir=baked_in_dir, config_dir=config_dir)


# ---------------------------------------------------------------------------
# 1. Baked-in defaults load correctly
# ---------------------------------------------------------------------------

def test_baked_in_defaults_load(tmp_path):
    _write(tmp_path / "app_config.yaml", """\
        server:
          api_port: 8000
        models:
          orchestrator: claude-sonnet-4-5
    """)
    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get("server.api_port") == 8000
    assert cfg.get("models.orchestrator") == "claude-sonnet-4-5"


def test_get_returns_default_when_key_missing(tmp_path):
    _write(tmp_path / "app_config.yaml", "server:\n  api_port: 8000\n")
    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get("nonexistent.key", default="fallback") == "fallback"


# ---------------------------------------------------------------------------
# 2. Local override deep-merges over defaults (not replaces)
# ---------------------------------------------------------------------------

def test_local_override_deep_merges(tmp_path):
    baked_dir = tmp_path / "baked"
    local_dir = tmp_path / "local"

    _write(baked_dir / "app_config.yaml", """\
        server:
          api_port: 8000
          mcp_port: 5001
        models:
          orchestrator: claude-sonnet-4-5
    """)
    _write(local_dir / "app_config.yaml", """\
        server:
          api_port: 9000
    """)

    cfg = _make_loader(baked_in_dir=baked_dir, config_dir=local_dir)
    cfg.load()

    # Overridden key
    assert cfg.get("server.api_port") == 9000
    # Untouched sibling key — not erased by override
    assert cfg.get("server.mcp_port") == 5001
    # Untouched top-level section
    assert cfg.get("models.orchestrator") == "claude-sonnet-4-5"


def test_multiple_yaml_files_merged(tmp_path):
    _write(tmp_path / "app_config.yaml", "server:\n  api_port: 8000\n")
    _write(tmp_path / "auth_config.yaml", "jwt:\n  secret: test-secret\n")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get("server.api_port") == 8000
    assert cfg.get("jwt.secret") == "test-secret"


# ---------------------------------------------------------------------------
# 3. Placeholder ${VAR} resolves from env var
# ---------------------------------------------------------------------------

def test_placeholder_resolves_from_env(tmp_path, monkeypatch):
    _write(tmp_path / "auth_config.yaml", "jwt:\n  secret: \"${TETHER_JWT_SECRET}\"\n")
    monkeypatch.setenv("TETHER_JWT_SECRET", "supersecret")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get("jwt.secret") == "supersecret"


def test_placeholder_in_nested_list_value(tmp_path, monkeypatch):
    _write(tmp_path / "auth_config.yaml",
           "cors:\n  allowed_origins: \"${TETHER_ALLOWED_ORIGINS}\"\n")
    monkeypatch.setenv("TETHER_ALLOWED_ORIGINS", "http://a.com,http://b.com")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get("cors.allowed_origins") == "http://a.com,http://b.com"


# ---------------------------------------------------------------------------
# 4. Placeholder ${VAR:-default} uses fallback when env var absent
# ---------------------------------------------------------------------------

def test_placeholder_default_used_when_env_absent(tmp_path, monkeypatch):
    _write(tmp_path / "auth_config.yaml",
           "cookie:\n  secure: \"${TETHER_COOKIE_SECURE:-true}\"\n")
    monkeypatch.delenv("TETHER_COOKIE_SECURE", raising=False)

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get("cookie.secure") == "true"


def test_placeholder_env_wins_over_default(tmp_path, monkeypatch):
    _write(tmp_path / "auth_config.yaml",
           "cookie:\n  secure: \"${TETHER_COOKIE_SECURE:-true}\"\n")
    monkeypatch.setenv("TETHER_COOKIE_SECURE", "false")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get("cookie.secure") == "false"


def test_placeholder_left_as_is_when_no_env_no_default(tmp_path, monkeypatch):
    """Unresolved ${VAR} with no default stays as-is (caught by validate if required)."""
    _write(tmp_path / "app_config.yaml",
           "some:\n  key: \"${MISSING_VAR}\"\n")
    monkeypatch.delenv("MISSING_VAR", raising=False)

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get("some.key") == "${MISSING_VAR}"


# ---------------------------------------------------------------------------
# 5. Required key validation fails hard when unresolved
# ---------------------------------------------------------------------------

def test_validate_raises_on_unresolved_required_key(tmp_path, monkeypatch):
    # jwt.secret is REQUIRED_KEYS — unresolved placeholder must raise at load()
    _write(tmp_path / "auth_config.yaml",
           "jwt:\n  secret: \"${TETHER_JWT_SECRET}\"\n")
    monkeypatch.delenv("TETHER_JWT_SECRET", raising=False)

    cfg = _make_loader(baked_in_dir=tmp_path)
    with pytest.raises(RuntimeError, match="jwt.secret"):
        cfg.load()


def test_validate_passes_when_required_key_resolved(tmp_path, monkeypatch):
    _write(tmp_path / "auth_config.yaml",
           "jwt:\n  secret: \"${TETHER_JWT_SECRET}\"\n")
    monkeypatch.setenv("TETHER_JWT_SECRET", "my-real-secret")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()  # should not raise

    assert cfg.get("jwt.secret") == "my-real-secret"


# ---------------------------------------------------------------------------
# 6. secrets.json compatibility shim
# ---------------------------------------------------------------------------

def test_secrets_json_shim_loads_jwt_secret(tmp_path, monkeypatch):
    """If auth_config.yaml absent in local dir but secrets.json present, use shim."""
    baked_dir = tmp_path / "baked"
    local_dir = tmp_path / "local"

    _write(baked_dir / "auth_config.yaml",
           "jwt:\n  secret: \"${TETHER_JWT_SECRET}\"\n")

    # secrets.json present, auth_config.yaml NOT present in local dir
    (local_dir).mkdir(parents=True, exist_ok=True)
    (local_dir / "secrets.json").write_text(json.dumps({
        "TETHER_JWT_SECRET": "from-secrets-json",
    }))

    monkeypatch.delenv("TETHER_JWT_SECRET", raising=False)

    cfg = _make_loader(baked_in_dir=baked_dir, config_dir=local_dir)
    cfg.load()

    assert cfg.get("jwt.secret") == "from-secrets-json"


def test_secrets_json_shim_maps_all_known_keys(tmp_path, monkeypatch):
    baked_dir = tmp_path / "baked"
    local_dir = tmp_path / "local"

    _write(baked_dir / "auth_config.yaml", """\
        jwt:
          secret: "${TETHER_JWT_SECRET}"
        cookie:
          secure: "${TETHER_COOKIE_SECURE:-true}"
        cors:
          allowed_origins: "${TETHER_ALLOWED_ORIGINS:-http://localhost:5173}"
        oauth:
          github:
            client_id: "${GITHUB_CLIENT_ID:-}"
          google:
            client_id: "${GOOGLE_CLIENT_ID:-}"
    """)
    _write(baked_dir / "integrations.yaml",
           "google_calendar:\n  callback_url: \"${GOOGLE_INTEGRATION_CALLBACK_URL:-}\"\n")

    (local_dir).mkdir(parents=True, exist_ok=True)
    (local_dir / "secrets.json").write_text(json.dumps({
        "TETHER_JWT_SECRET": "jwt-val",
        "TETHER_COOKIE_SECURE": "false",
        "TETHER_ALLOWED_ORIGINS": "https://example.com",
        "GITHUB_CLIENT_ID": "gh-id",
        "GOOGLE_CLIENT_ID": "goog-id",
        "GOOGLE_INTEGRATION_CALLBACK_URL": "https://example.com/cb",
    }))

    for key in ["TETHER_JWT_SECRET", "TETHER_COOKIE_SECURE", "TETHER_ALLOWED_ORIGINS",
                "GITHUB_CLIENT_ID", "GOOGLE_CLIENT_ID", "GOOGLE_INTEGRATION_CALLBACK_URL"]:
        monkeypatch.delenv(key, raising=False)

    cfg = _make_loader(baked_in_dir=baked_dir, config_dir=local_dir)
    cfg.load()

    assert cfg.get("jwt.secret") == "jwt-val"
    assert cfg.get("cookie.secure") == "false"
    assert cfg.get("cors.allowed_origins") == "https://example.com"
    assert cfg.get("oauth.github.client_id") == "gh-id"
    assert cfg.get("oauth.google.client_id") == "goog-id"


def test_secrets_json_shim_skipped_when_auth_yaml_present(tmp_path, monkeypatch):
    """Local auth_config.yaml takes precedence — secrets.json shim is NOT applied."""
    baked_dir = tmp_path / "baked"
    local_dir = tmp_path / "local"

    _write(baked_dir / "auth_config.yaml",
           "jwt:\n  secret: \"${TETHER_JWT_SECRET}\"\n")
    _write(local_dir / "auth_config.yaml",
           "jwt:\n  secret: real-secret-from-yaml\n")

    (local_dir / "secrets.json").write_text(json.dumps({
        "TETHER_JWT_SECRET": "from-secrets-json",
    }))
    monkeypatch.delenv("TETHER_JWT_SECRET", raising=False)

    cfg = _make_loader(baked_in_dir=baked_dir, config_dir=local_dir)
    cfg.load()

    assert cfg.get("jwt.secret") == "real-secret-from-yaml"


# ---------------------------------------------------------------------------
# 7. get_bool() handles various truthy/falsy representations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("true", True),
    ("True", True),
    ("TRUE", True),
    ("1", True),
    (True, True),
    ("false", False),
    ("False", False),
    ("FALSE", False),
    ("0", False),
    (False, False),
])
def test_get_bool_handles_all_representations(tmp_path, value, expected):
    _write(tmp_path / "app_config.yaml", f"feature:\n  enabled: {json.dumps(value)}\n")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get_bool("feature.enabled") is expected


def test_get_bool_returns_default_when_missing(tmp_path):
    _write(tmp_path / "app_config.yaml", "server:\n  api_port: 8000\n")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get_bool("feature.missing", default=True) is True
    assert cfg.get_bool("feature.missing", default=False) is False


# ---------------------------------------------------------------------------
# 8. get_list() splits comma-separated strings
# ---------------------------------------------------------------------------

def test_get_list_splits_comma_separated(tmp_path):
    _write(tmp_path / "auth_config.yaml",
           "cors:\n  allowed_origins: \"http://a.com, http://b.com, http://c.com\"\n")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get_list("cors.allowed_origins") == [
        "http://a.com", "http://b.com", "http://c.com"
    ]


def test_get_list_returns_list_as_is(tmp_path):
    _write(tmp_path / "app_config.yaml",
           "items:\n  - one\n  - two\n  - three\n")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get_list("items") == ["one", "two", "three"]


def test_get_list_returns_default_when_missing(tmp_path):
    _write(tmp_path / "app_config.yaml", "server:\n  api_port: 8000\n")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()

    assert cfg.get_list("missing.key", default=["x"]) == ["x"]


# ---------------------------------------------------------------------------
# 9. Remote provider stub raises NotImplementedError
# ---------------------------------------------------------------------------

def test_remote_provider_stub_raises(tmp_path, monkeypatch):
    _write(tmp_path / "auth_config.yaml",
           "jwt:\n  secret: some-secret\n")
    monkeypatch.setenv("TETHER_REMOTE_PROVIDER", "tigris")
    monkeypatch.setenv("TETHER_CONFIG_BUCKET", "test-bucket")

    cfg = _make_loader(baked_in_dir=tmp_path, config_dir=None)
    with pytest.raises(NotImplementedError):
        cfg.load()


# ---------------------------------------------------------------------------
# 10. load() is idempotent (calling twice doesn't raise)
# ---------------------------------------------------------------------------

def test_load_is_idempotent(tmp_path, monkeypatch):
    _write(tmp_path / "auth_config.yaml",
           "jwt:\n  secret: stable-secret\n")

    cfg = _make_loader(baked_in_dir=tmp_path)
    cfg.load()
    cfg.load()  # should not raise

    assert cfg.get("jwt.secret") == "stable-secret"
