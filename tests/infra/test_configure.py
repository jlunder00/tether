"""
Tests for scripts/configure.py — Tether configuration helper.

Covers:
  - deep_merge: recursive dict merge, list replacement, no mutation
  - set_dotted_key: nested key creation and update
  - atomic_write: file creation, atomic semantics, parent dir creation
  - apply_category: correct YAML paths per category, deep-merge semantics,
                    template fallback, .env update for db category
  - run_install: JWT auto-generation and explicit JWT use
  - interactive mode: empty-string arg prompts and skips empty input
"""

import pytest
import yaml
from pathlib import Path


# ── deep_merge ───────────────────────────────────────────────────────────────

class TestDeepMerge:
    def test_simple_override(self):
        from configure import deep_merge
        assert deep_merge({"a": 1, "b": 2}, {"b": 3, "c": 4}) == {"a": 1, "b": 3, "c": 4}

    def test_nested_dicts_merged(self):
        from configure import deep_merge
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 0}}
        assert deep_merge(base, override) == {"a": {"x": 1, "y": 99, "z": 0}, "b": 3}

    def test_lists_replaced_not_merged(self):
        from configure import deep_merge
        assert deep_merge({"items": [1, 2, 3]}, {"items": [4, 5]}) == {"items": [4, 5]}

    def test_does_not_mutate_base(self):
        from configure import deep_merge
        base = {"a": {"x": 1}}
        deep_merge(base, {"a": {"y": 2}})
        assert base == {"a": {"x": 1}}

    def test_empty_override_returns_copy(self):
        from configure import deep_merge
        base = {"a": 1}
        result = deep_merge(base, {})
        assert result == {"a": 1}
        assert result is not base


# ── set_dotted_key ───────────────────────────────────────────────────────────

class TestSetDottedKey:
    def test_simple_key(self):
        from configure import set_dotted_key
        d = {}
        set_dotted_key(d, "foo", "bar")
        assert d == {"foo": "bar"}

    def test_nested_key_creates_dicts(self):
        from configure import set_dotted_key
        d = {}
        set_dotted_key(d, "oauth.github.client_id", "my-id")
        assert d == {"oauth": {"github": {"client_id": "my-id"}}}

    def test_merges_into_existing_sibling(self):
        from configure import set_dotted_key
        d = {"oauth": {"github": {"client_id": "old"}}}
        set_dotted_key(d, "oauth.github.client_secret", "sec")
        assert d["oauth"]["github"]["client_id"] == "old"
        assert d["oauth"]["github"]["client_secret"] == "sec"

    def test_overwrites_existing_value(self):
        from configure import set_dotted_key
        d = {"jwt": {"secret": "old"}}
        set_dotted_key(d, "jwt.secret", "new")
        assert d["jwt"]["secret"] == "new"


# ── atomic_write ─────────────────────────────────────────────────────────────

class TestAtomicWrite:
    def test_creates_file(self, tmp_path):
        from configure import atomic_write
        target = tmp_path / "out.yaml"
        atomic_write(target, "hello: world\n")
        assert target.read_text() == "hello: world\n"

    def test_overwrites_existing(self, tmp_path):
        from configure import atomic_write
        target = tmp_path / "out.yaml"
        target.write_text("old: content\n")
        atomic_write(target, "new: content\n")
        assert target.read_text() == "new: content\n"

    def test_creates_parent_dirs(self, tmp_path):
        from configure import atomic_write
        target = tmp_path / "subdir" / "out.yaml"
        atomic_write(target, "x: 1\n")
        assert target.exists()

    def test_no_leftover_tmp_file(self, tmp_path):
        from configure import atomic_write
        target = tmp_path / "out.yaml"
        atomic_write(target, "x: 1\n")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


# ── apply_category — auth ────────────────────────────────────────────────────

class TestApplyCategoryAuth:
    def test_writes_jwt_secret(self, tmp_path):
        from configure import apply_category
        apply_category(
            category="auth",
            kvs={"TETHER_JWT_SECRET": "s3cr3t"},
            config_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        result = yaml.safe_load((tmp_path / "auth_config.yaml").read_text())
        assert result["jwt"]["secret"] == "s3cr3t"

    def test_writes_cookie_secure(self, tmp_path):
        from configure import apply_category
        apply_category(
            category="auth",
            kvs={"TETHER_COOKIE_SECURE": "false"},
            config_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        result = yaml.safe_load((tmp_path / "auth_config.yaml").read_text())
        assert result["cookie"]["secure"] == "false"

    def test_writes_allowed_origins(self, tmp_path):
        from configure import apply_category
        apply_category(
            category="auth",
            kvs={"TETHER_ALLOWED_ORIGINS": "https://example.com"},
            config_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        result = yaml.safe_load((tmp_path / "auth_config.yaml").read_text())
        assert result["cors"]["allowed_origins"] == "https://example.com"

    def test_preserves_existing_unrelated_keys(self, tmp_path):
        from configure import apply_category
        (tmp_path / "auth_config.yaml").write_text(
            "jwt:\n  secret: keep-me\ncors:\n  allowed_origins: http://localhost\n"
        )
        apply_category(
            category="auth",
            kvs={"TETHER_COOKIE_SECURE": "true"},
            config_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        result = yaml.safe_load((tmp_path / "auth_config.yaml").read_text())
        assert result["jwt"]["secret"] == "keep-me"
        assert result["cookie"]["secure"] == "true"


# ── apply_category — google ──────────────────────────────────────────────────

class TestApplyCategoryGoogle:
    def test_writes_to_correct_yaml_paths(self, tmp_path):
        from configure import apply_category
        apply_category(
            category="google",
            kvs={
                "GOOGLE_CLIENT_ID": "gid",
                "GOOGLE_CLIENT_SECRET": "gsec",
                "GOOGLE_CALLBACK_URL": "http://cb/google",
                "GOOGLE_INTEGRATION_CALLBACK_URL": "http://cb/integration",
            },
            config_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        result = yaml.safe_load((tmp_path / "auth_config.yaml").read_text())
        assert result["oauth"]["google"]["client_id"] == "gid"
        assert result["oauth"]["google"]["client_secret"] == "gsec"
        assert result["oauth"]["google"]["callback_url"] == "http://cb/google"
        assert result["oauth"]["google"]["integration_callback_url"] == "http://cb/integration"

    def test_does_not_clobber_github_keys(self, tmp_path):
        from configure import apply_category
        (tmp_path / "auth_config.yaml").write_text(
            "oauth:\n  github:\n    client_id: gh-id\n"
        )
        apply_category(
            category="google",
            kvs={"GOOGLE_CLIENT_ID": "gid"},
            config_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        result = yaml.safe_load((tmp_path / "auth_config.yaml").read_text())
        assert result["oauth"]["github"]["client_id"] == "gh-id"
        assert result["oauth"]["google"]["client_id"] == "gid"


# ── apply_category — github ──────────────────────────────────────────────────

class TestApplyCategoryGitHub:
    def test_writes_to_correct_yaml_paths(self, tmp_path):
        from configure import apply_category
        apply_category(
            category="github",
            kvs={
                "GITHUB_CLIENT_ID": "ghid",
                "GITHUB_CLIENT_SECRET": "ghsec",
                "GITHUB_CALLBACK_URL": "http://cb/github",
            },
            config_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        result = yaml.safe_load((tmp_path / "auth_config.yaml").read_text())
        assert result["oauth"]["github"]["client_id"] == "ghid"
        assert result["oauth"]["github"]["client_secret"] == "ghsec"
        assert result["oauth"]["github"]["callback_url"] == "http://cb/github"


# ── apply_category — telegram ────────────────────────────────────────────────

class TestApplyCategoryTelegram:
    def test_writes_to_app_config(self, tmp_path):
        from configure import apply_category
        apply_category(
            category="telegram",
            kvs={"TELEGRAM_BOT_TOKEN": "123:ABC", "TELEGRAM_CHAT_ID": "456"},
            config_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        result = yaml.safe_load((tmp_path / "app_config.yaml").read_text())
        assert result["telegram"]["bot_token"] == "123:ABC"
        assert result["telegram"]["chat_id"] == "456"


# ── apply_category — db ──────────────────────────────────────────────────────

class TestApplyCategoryDb:
    def test_writes_env_file(self, tmp_path):
        from configure import apply_category
        apply_category(
            category="db",
            kvs={"POSTGRES_PASSWORD": "pgpass", "TETHER_APP_PASSWORD": "apppass"},
            config_dir=tmp_path,
            compose_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        content = (tmp_path / ".env").read_text()
        assert "POSTGRES_PASSWORD=pgpass" in content
        assert "TETHER_APP_PASSWORD=apppass" in content

    def test_preserves_unrelated_env_keys(self, tmp_path):
        from configure import apply_category
        (tmp_path / ".env").write_text("IMAGE_TAG=latest\nPOSTGRES_PASSWORD=old\n")
        apply_category(
            category="db",
            kvs={"POSTGRES_PASSWORD": "new-pass"},
            config_dir=tmp_path,
            compose_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        content = (tmp_path / ".env").read_text()
        assert "POSTGRES_PASSWORD=new-pass" in content
        assert "IMAGE_TAG=latest" in content

    def test_does_not_write_yaml_file(self, tmp_path):
        from configure import apply_category
        apply_category(
            category="db",
            kvs={"POSTGRES_PASSWORD": "pgpass"},
            config_dir=tmp_path,
            compose_dir=tmp_path,
            template_dir=None,
            interactive=False,
        )
        # Should NOT create a db_config.yaml or any yaml file
        yaml_files = list(tmp_path.glob("*.yaml"))
        assert yaml_files == []


# ── Template fallback ────────────────────────────────────────────────────────

class TestTemplateFallback:
    def test_loads_from_template_when_config_missing(self, tmp_path):
        from configure import apply_category
        config_dir = tmp_path / "config_dir"
        config_dir.mkdir()
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        (template_dir / "auth_config.yaml").write_text(
            "jwt:\n  secret: ''\ncors:\n  allowed_origins: http://localhost\n"
        )
        apply_category(
            category="auth",
            kvs={"TETHER_JWT_SECRET": "new-secret"},
            config_dir=config_dir,
            template_dir=template_dir,
            interactive=False,
        )
        result = yaml.safe_load((config_dir / "auth_config.yaml").read_text())
        assert result["jwt"]["secret"] == "new-secret"
        assert result["cors"]["allowed_origins"] == "http://localhost"

    def test_creates_fresh_when_no_template(self, tmp_path):
        from configure import apply_category
        config_dir = tmp_path / "config_dir"
        config_dir.mkdir()
        apply_category(
            category="auth",
            kvs={"TETHER_JWT_SECRET": "fresh-secret"},
            config_dir=config_dir,
            template_dir=None,
            interactive=False,
        )
        result = yaml.safe_load((config_dir / "auth_config.yaml").read_text())
        assert result["jwt"]["secret"] == "fresh-secret"


# ── run_install ──────────────────────────────────────────────────────────────

class TestRunInstall:
    def test_generates_jwt_secret_when_none_provided(self, tmp_path):
        from configure import run_install
        config_dir = tmp_path / "tether-config"
        run_install(
            config_dir=config_dir,
            compose_dir=tmp_path,
            template_dir=None,
            provided_jwt=None,
        )
        result = yaml.safe_load((config_dir / "auth_config.yaml").read_text())
        jwt = result["jwt"]["secret"]
        assert jwt != ""
        assert len(jwt) == 64  # secrets.token_hex(32) → 64 hex chars

    def test_uses_provided_jwt(self, tmp_path):
        from configure import run_install
        config_dir = tmp_path / "tether-config"
        run_install(
            config_dir=config_dir,
            compose_dir=tmp_path,
            template_dir=None,
            provided_jwt="explicit-secret-value",
        )
        result = yaml.safe_load((config_dir / "auth_config.yaml").read_text())
        assert result["jwt"]["secret"] == "explicit-secret-value"

    def test_creates_config_dir_if_missing(self, tmp_path):
        from configure import run_install
        config_dir = tmp_path / "does-not-exist"
        assert not config_dir.exists()
        run_install(
            config_dir=config_dir,
            compose_dir=tmp_path,
            template_dir=None,
            provided_jwt="x",
        )
        assert config_dir.exists()


# ── Interactive mode ─────────────────────────────────────────────────────────

class TestInteractiveMode:
    def test_empty_input_leaves_existing_value(self, tmp_path, monkeypatch):
        from configure import apply_category
        (tmp_path / "auth_config.yaml").write_text("jwt:\n  secret: keep-this\n")
        monkeypatch.setattr("builtins.input", lambda _: "")
        apply_category(
            category="auth",
            kvs={"TETHER_JWT_SECRET": ""},
            config_dir=tmp_path,
            template_dir=None,
            interactive=True,
        )
        result = yaml.safe_load((tmp_path / "auth_config.yaml").read_text())
        assert result["jwt"]["secret"] == "keep-this"

    def test_provided_input_sets_value(self, tmp_path, monkeypatch):
        from configure import apply_category
        responses = iter(["new-jwt-value"])
        monkeypatch.setattr("builtins.input", lambda _: next(responses))
        apply_category(
            category="auth",
            kvs={"TETHER_JWT_SECRET": ""},
            config_dir=tmp_path,
            template_dir=None,
            interactive=True,
        )
        result = yaml.safe_load((tmp_path / "auth_config.yaml").read_text())
        assert result["jwt"]["secret"] == "new-jwt-value"

    def test_non_empty_kvs_do_not_prompt(self, tmp_path, monkeypatch):
        """When a value is already provided (non-empty), input() is never called."""
        from configure import apply_category
        call_count = {"n": 0}

        def fail_if_called(prompt):
            call_count["n"] += 1
            return ""

        monkeypatch.setattr("builtins.input", fail_if_called)
        apply_category(
            category="auth",
            kvs={"TETHER_JWT_SECRET": "already-set"},
            config_dir=tmp_path,
            template_dir=None,
            interactive=True,
        )
        assert call_count["n"] == 0
