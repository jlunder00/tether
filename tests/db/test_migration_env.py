"""Tests for db/migrations/env.py — URL resolution for alembic connections.

Migrations require DDL privileges (CREATE INDEX, ALTER TABLE, etc.) which
means they must connect as the table owner, not as the app role (tether_app).
ADMIN_DATABASE_URL carries owner credentials; DATABASE_URL carries app credentials.
env.py must prefer ADMIN_DATABASE_URL so migrations never run as tether_app.
"""
from __future__ import annotations

import importlib.util
import logging.config
import os
import pathlib
import sys
import types

import pytest

_ENV_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "db" / "migrations" / "env.py"
)


def _resolved_url(monkeypatch, env_vars: dict) -> str:
    """Load env.py in a fully-stubbed environment and return the URL it selects.

    We only care about the top-level URL-selection logic (the three lines that
    read env vars and call config.set_main_option). Everything else — alembic
    internals, sqlalchemy engine creation, actual DB connections — is stubbed
    out so the test runs without any infrastructure.
    """
    # Set / clear env vars
    for k in ("DATABASE_URL", "ADMIN_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env_vars.items():
        monkeypatch.setenv(k, v)

    resolved: dict[str, str] = {}

    fake_engine = types.SimpleNamespace(connect=_null_ctx)
    fake_pool = types.SimpleNamespace(NullPool=None)

    # Minimal fake alembic.context module — only the attributes env.py touches
    fake_config = types.SimpleNamespace(
        config_file_name=None,
        config_ini_section="alembic",          # used by get_section in run_migrations_online
        set_main_option=lambda key, val: resolved.__setitem__(key, val),
        get_main_option=lambda key: resolved.get(key, ""),
        get_section=lambda *a, **kw: {},
    )
    fake_context_mod = types.ModuleType("alembic.context")
    fake_context_mod.config = fake_config          # context.config
    fake_context_mod.is_offline_mode = lambda: False
    fake_context_mod.configure = lambda **kw: None
    fake_context_mod.begin_transaction = _null_ctx
    fake_context_mod.run_migrations = lambda: None

    # Minimal fake sqlalchemy module — engine_from_config and pool must be importable
    fake_sa = types.ModuleType("sqlalchemy")
    fake_sa.engine_from_config = lambda *a, **kw: fake_engine
    fake_sa.pool = fake_pool

    # Patch sys.modules so env.py imports our stubs
    monkeypatch.setitem(sys.modules, "sqlalchemy", fake_sa)
    monkeypatch.setitem(sys.modules, "alembic", types.ModuleType("alembic"))
    monkeypatch.setitem(sys.modules, "alembic.context", fake_context_mod)

    # fileConfig is a no-op (no real ini file)
    monkeypatch.setattr(logging.config, "fileConfig", lambda *a, **kw: None)

    # Remove cached module if present from a previous run
    mod_name = "db.migrations.env_test_target"
    sys.modules.pop(mod_name, None)

    spec = importlib.util.spec_from_file_location(mod_name, _ENV_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    return resolved.get("sqlalchemy.url", "")


def _null_ctx(*a, **kw):
    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): pass
    return _Ctx()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_admin_database_url_takes_precedence_over_database_url(monkeypatch):
    """ADMIN_DATABASE_URL must win when both vars are set.

    Migrations need owner-level DDL privileges — they must connect as tether
    (table owner), not tether_app. If DATABASE_URL wins, migrations run as
    tether_app and fail with InsufficientPrivilege on CREATE INDEX / ALTER TABLE.
    """
    url = _resolved_url(monkeypatch, {
        "DATABASE_URL": "postgresql://tether_app:pw@localhost/tether",
        "ADMIN_DATABASE_URL": "postgresql://tether:adminpw@localhost/tether",
    })
    assert url == "postgresql://tether:adminpw@localhost/tether", (
        f"Expected ADMIN_DATABASE_URL to win, got: {url!r}"
    )


def test_database_url_used_as_fallback_when_admin_url_absent(monkeypatch):
    """Falls back to DATABASE_URL when ADMIN_DATABASE_URL is not set."""
    url = _resolved_url(monkeypatch, {
        "DATABASE_URL": "postgresql://tether_app:pw@localhost/tether",
    })
    assert url == "postgresql://tether_app:pw@localhost/tether"


def test_neither_url_set_leaves_alembic_ini_default(monkeypatch):
    """When neither env var is set, env.py must not override the ini URL."""
    url = _resolved_url(monkeypatch, {})
    assert url == ""
