"""Tests for interactive_agent_layer.__main__ production Layer construction.

Task #3 (D): the production entrypoint must wire premium DB-bound functions
(permission grants + scope gating) into Layer(...) when tether_premium is
installed and DATABASE_URL is configured — and must stay a strict no-op
(bare Layer, no gating) when either is absent. This is the "prod Layer
construction" boundary flagged in the wiring plan.
"""
from __future__ import annotations

import sys
from unittest import mock

import pytest


class _FakePoolClient:
    pass


class _FakeWSPublisher:
    pass


def _fake_premium_modules(check_fn, insert_fn, hop_fn, resolve_path_fn, resolve_conv_fn):
    """Build fake tether_premium.bot.permission_grants / scope_grants modules."""
    grants_mod = mock.MagicMock()
    grants_mod.get_permission_grant_fns = mock.MagicMock(
        return_value=(check_fn, insert_fn)
    )

    scope_mod = mock.MagicMock()
    scope_mod.get_scope_fns = mock.MagicMock(
        return_value=(hop_fn, resolve_path_fn, resolve_conv_fn)
    )

    return grants_mod, scope_mod


class TestGetPremiumLayerKwargs:
    """_get_premium_layer_kwargs(db_pool) -> dict, {} when tether_premium absent."""

    def test_returns_empty_dict_when_tether_premium_not_installed(self, monkeypatch):
        from interactive_agent_layer import __main__ as main_mod

        # Simulate the packages not being importable.
        monkeypatch.setitem(sys.modules, "tether_premium.bot.permission_grants", None)
        monkeypatch.setitem(sys.modules, "tether_premium.bot.scope_grants", None)

        kwargs = main_mod._get_premium_layer_kwargs(object())
        assert kwargs == {}

    def test_returns_bound_fns_when_tether_premium_installed(self, monkeypatch):
        from interactive_agent_layer import __main__ as main_mod

        check_fn, insert_fn = object(), object()
        hop_fn, resolve_path_fn, resolve_conv_fn = object(), object(), object()
        grants_mod, scope_mod = _fake_premium_modules(
            check_fn, insert_fn, hop_fn, resolve_path_fn, resolve_conv_fn
        )
        monkeypatch.setitem(sys.modules, "tether_premium", mock.MagicMock())
        monkeypatch.setitem(sys.modules, "tether_premium.bot", mock.MagicMock())
        monkeypatch.setitem(
            sys.modules, "tether_premium.bot.permission_grants", grants_mod
        )
        monkeypatch.setitem(sys.modules, "tether_premium.bot.scope_grants", scope_mod)

        pool = object()
        kwargs = main_mod._get_premium_layer_kwargs(pool)

        assert kwargs["check_grant_fn"] is check_fn
        assert kwargs["insert_grant_fn"] is insert_fn
        assert kwargs["hop_distance_fn"] is hop_fn
        assert kwargs["resolve_node_path_fn"] is resolve_path_fn
        assert kwargs["resolve_conversation_scope_fn"] is resolve_conv_fn
        grants_mod.get_permission_grant_fns.assert_called_once_with(pool)
        scope_mod.get_scope_fns.assert_called_once_with(pool)


class TestBuildLayer:
    """_build_layer(pool_client, publisher) -> Layer, wired via premium when available."""

    async def test_no_database_url_produces_bare_layer(self, monkeypatch):
        """No DATABASE_URL → no DB pool → no premium fns, even if tether_premium
        is importable — fully backwards compatible."""
        from interactive_agent_layer import __main__ as main_mod

        monkeypatch.delenv("DATABASE_URL", raising=False)

        layer = await main_mod._build_layer(_FakePoolClient(), _FakeWSPublisher())

        assert layer.check_grant_fn is None
        assert layer.insert_grant_fn is None
        assert layer.hop_distance_fn is None
        assert layer.resolve_node_path_fn is None
        assert layer.resolve_conversation_scope_fn is None

    async def test_database_url_and_premium_present_wires_all_fns(self, monkeypatch):
        """DATABASE_URL set + tether_premium importable → Layer gets all five fns."""
        from interactive_agent_layer import __main__ as main_mod

        monkeypatch.setenv("DATABASE_URL", "postgresql://fake/db")

        fake_pool = object()
        create_pool_mock = mock.AsyncMock(return_value=fake_pool)
        monkeypatch.setattr(main_mod, "_create_db_pool", create_pool_mock)

        check_fn, insert_fn = object(), object()
        hop_fn, resolve_path_fn, resolve_conv_fn = object(), object(), object()
        monkeypatch.setattr(
            main_mod,
            "_get_premium_layer_kwargs",
            lambda pool: {
                "check_grant_fn": check_fn,
                "insert_grant_fn": insert_fn,
                "hop_distance_fn": hop_fn,
                "resolve_node_path_fn": resolve_path_fn,
                "resolve_conversation_scope_fn": resolve_conv_fn,
            } if pool is fake_pool else {},
        )

        layer = await main_mod._build_layer(_FakePoolClient(), _FakeWSPublisher())

        assert layer.check_grant_fn is check_fn
        assert layer.insert_grant_fn is insert_fn
        assert layer.hop_distance_fn is hop_fn
        assert layer.resolve_node_path_fn is resolve_path_fn
        assert layer.resolve_conversation_scope_fn is resolve_conv_fn

    async def test_db_pool_creation_failure_falls_back_to_bare_layer(self, monkeypatch):
        """DB pool creation raising must not crash startup — falls back to no gating."""
        from interactive_agent_layer import __main__ as main_mod

        monkeypatch.setenv("DATABASE_URL", "postgresql://fake/db")
        monkeypatch.setattr(
            main_mod, "_create_db_pool", mock.AsyncMock(side_effect=Exception("no db"))
        )

        layer = await main_mod._build_layer(_FakePoolClient(), _FakeWSPublisher())

        assert layer.check_grant_fn is None
        assert layer.hop_distance_fn is None
