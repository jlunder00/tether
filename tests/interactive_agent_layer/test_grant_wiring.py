"""Tests for check_grant_fn / insert_grant_fn wiring into Layer and PermissionGate.

These tests verify that:
1. Layer.__init__ accepts check_grant_fn and insert_grant_fn kwargs
2. Layer passes them to PermissionGate when constructing it in run_turn
3. PermissionGate.__init__ accepts check_grant_fn and insert_grant_fn kwargs
4. PermissionGate stores them as accessible attributes

Written TDD — tests were written before implementation.
Plumbing PR scope: accept and thread the fns; _dispatch usage is a follow-up.
"""
from __future__ import annotations

import asyncio
import pathlib
from unittest import mock

import pytest

from interactive_agent_layer.session import Layer, Session
from interactive_agent_layer.permissions import PermissionGate
from interactive_agent_layer.translation import TranslationTable
from interactive_agent_layer.ws_publisher import WSPublisher


YAML_PATH = (
    pathlib.Path(__file__).parent.parent.parent / "config" / "agent_translations.yaml"
)


@pytest.fixture
def table():
    return TranslationTable.from_yaml(YAML_PATH)


@pytest.fixture
def session():
    return Session(
        session_id="sess-wiring",
        user_id="user-wiring",
        user_ws_id="ws-wiring",
        agent_version="tether-agent-2.0",
        options={},
    )


# ---------------------------------------------------------------------------
# PermissionGate — accepts grant fn parameters
# ---------------------------------------------------------------------------


class TestPermissionGateGrantFnParams:
    """PermissionGate.__init__ accepts check_grant_fn and insert_grant_fn."""

    def test_accepts_check_grant_fn(self, table, session):
        """PermissionGate can be constructed with a check_grant_fn keyword arg."""
        async def my_check_fn(user_id, conv_id, target, kind): return True

        gate = PermissionGate(
            translation_table=table,
            session=session,
            outbound_events=asyncio.Queue(),
            check_grant_fn=my_check_fn,
        )
        assert gate._check_grant_fn is my_check_fn

    def test_accepts_insert_grant_fn(self, table, session):
        """PermissionGate can be constructed with an insert_grant_fn keyword arg."""
        async def my_insert_fn(user_id, conv_id, target, kind): pass

        gate = PermissionGate(
            translation_table=table,
            session=session,
            outbound_events=asyncio.Queue(),
            insert_grant_fn=my_insert_fn,
        )
        assert gate._insert_grant_fn is my_insert_fn

    def test_both_fns_default_to_none(self, table, session):
        """check_grant_fn and insert_grant_fn default to None when not provided."""
        gate = PermissionGate(
            translation_table=table,
            session=session,
            outbound_events=asyncio.Queue(),
        )
        assert gate._check_grant_fn is None
        assert gate._insert_grant_fn is None

    def test_accepts_both_fns_simultaneously(self, table, session):
        """PermissionGate stores both fns when both are provided."""
        async def check_fn(u, c, t, k): return False
        async def insert_fn(u, c, t, k): pass

        gate = PermissionGate(
            translation_table=table,
            session=session,
            outbound_events=asyncio.Queue(),
            check_grant_fn=check_fn,
            insert_grant_fn=insert_fn,
        )
        assert gate._check_grant_fn is check_fn
        assert gate._insert_grant_fn is insert_fn


# ---------------------------------------------------------------------------
# Layer — accepts grant fn parameters
# ---------------------------------------------------------------------------


class TestLayerGrantFnParams:
    """Layer.__init__ accepts check_grant_fn and insert_grant_fn."""

    def _make_layer(self, check_fn=None, insert_fn=None):
        from tests.interactive_agent_layer.conftest import MockPoolClient
        return Layer(
            pool_client=MockPoolClient(),
            ws_publisher=WSPublisher(),
            check_grant_fn=check_fn,
            insert_grant_fn=insert_fn,
        )

    def test_accepts_check_grant_fn(self):
        """Layer stores check_grant_fn passed at construction."""
        async def check_fn(u, c, t, k): return True
        layer = self._make_layer(check_fn=check_fn)
        assert layer.check_grant_fn is check_fn

    def test_accepts_insert_grant_fn(self):
        """Layer stores insert_grant_fn passed at construction."""
        async def insert_fn(u, c, t, k): pass
        layer = self._make_layer(insert_fn=insert_fn)
        assert layer.insert_grant_fn is insert_fn

    def test_grant_fns_default_to_none(self):
        """Both grant fns default to None when not provided."""
        layer = self._make_layer()
        assert layer.check_grant_fn is None
        assert layer.insert_grant_fn is None


# ---------------------------------------------------------------------------
# Layer.run_turn — passes grant fns to PermissionGate
# ---------------------------------------------------------------------------


class TestLayerPassesGrantFnsToGate:
    """Layer.run_turn constructs PermissionGate with grant fns from Layer."""

    @pytest.mark.asyncio
    async def test_run_turn_passes_check_grant_fn_to_gate(self, monkeypatch):
        """PermissionGate constructed in run_turn receives check_grant_fn from Layer."""
        async def check_fn(u, c, t, k): return True

        from tests.interactive_agent_layer.conftest import MockPoolClient
        layer = Layer(
            pool_client=MockPoolClient(),
            ws_publisher=WSPublisher(),
            translation_table=TranslationTable.from_yaml(YAML_PATH),
            check_grant_fn=check_fn,
        )

        session = layer.create_session(
            user_id="u1", user_ws_id="ws1",
            agent_version="v1", options={},
        )

        captured_gates: list[PermissionGate] = []

        original_init = PermissionGate.__init__

        def capture_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            captured_gates.append(self)

        monkeypatch.setattr(PermissionGate, "__init__", capture_init)

        events = []
        async for event in layer.run_turn(session.session_id, "hello"):
            events.append(event)

        assert len(captured_gates) == 1, "PermissionGate should be constructed once per run_turn"
        assert captured_gates[0]._check_grant_fn is check_fn

    @pytest.mark.asyncio
    async def test_run_turn_passes_insert_grant_fn_to_gate(self, monkeypatch):
        """PermissionGate constructed in run_turn receives insert_grant_fn from Layer."""
        async def insert_fn(u, c, t, k): pass

        from tests.interactive_agent_layer.conftest import MockPoolClient
        layer = Layer(
            pool_client=MockPoolClient(),
            ws_publisher=WSPublisher(),
            translation_table=TranslationTable.from_yaml(YAML_PATH),
            insert_grant_fn=insert_fn,
        )

        session = layer.create_session(
            user_id="u2", user_ws_id="ws2",
            agent_version="v1", options={},
        )

        captured_gates: list[PermissionGate] = []

        original_init = PermissionGate.__init__

        def capture_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            captured_gates.append(self)

        monkeypatch.setattr(PermissionGate, "__init__", capture_init)

        events = []
        async for event in layer.run_turn(session.session_id, "hello"):
            events.append(event)

        assert len(captured_gates) == 1
        assert captured_gates[0]._insert_grant_fn is insert_fn

    @pytest.mark.asyncio
    async def test_run_turn_passes_none_when_no_grant_fns(self, monkeypatch):
        """PermissionGate._check_grant_fn/_insert_grant_fn are None when Layer has none."""
        from tests.interactive_agent_layer.conftest import MockPoolClient
        layer = Layer(
            pool_client=MockPoolClient(),
            ws_publisher=WSPublisher(),
            translation_table=TranslationTable.from_yaml(YAML_PATH),
        )

        session = layer.create_session(
            user_id="u3", user_ws_id="ws3",
            agent_version="v1", options={},
        )

        captured_gates: list[PermissionGate] = []
        original_init = PermissionGate.__init__

        def capture_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            captured_gates.append(self)

        monkeypatch.setattr(PermissionGate, "__init__", capture_init)

        async for _ in layer.run_turn(session.session_id, "hello"):
            pass

        assert len(captured_gates) == 1
        assert captured_gates[0]._check_grant_fn is None
        assert captured_gates[0]._insert_grant_fn is None
