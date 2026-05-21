"""Tests for PermissionGate (TDD — written before implementation)."""
from __future__ import annotations

import asyncio
import pathlib
from unittest.mock import MagicMock

import pytest

from interactive_agent_layer.permissions import (
    PermissionGate,
    PermissionResultAllow,
    PermissionResultDeny,
)
from interactive_agent_layer.session import Session
from interactive_agent_layer.translation import TranslationTable


@pytest.fixture(autouse=True)
def patch_permission_timeout(monkeypatch):
    """Avoid loading the real config (needs jwt.secret). Default to a generous timeout."""
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 30,
    )


@pytest.fixture
def table():
    yaml_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "config"
        / "agent_translations.yaml"
    )
    return TranslationTable.from_yaml(yaml_path)


def _make_blocking_ws():
    """
    Return a mock ws whose push() blocks until unblocked.

    Attributes:
        ws.push_event   — asyncio.Event; set when push() is called
        ws.release_event — asyncio.Event; push() awaits this before returning
        ws.calls        — list of (ws_id, event) tuples
    """
    push_event = asyncio.Event()
    release_event = asyncio.Event()
    calls = []

    async def _push(ws_id, event):
        calls.append((ws_id, event))
        push_event.set()
        await release_event.wait()

    ws = MagicMock()
    ws.push = _push
    ws.push_event = push_event
    ws.release_event = release_event
    ws.calls = calls
    return ws


@pytest.fixture
def mock_ws():
    """Simple non-blocking mock ws for tests that don't need interception."""
    ws = MagicMock()

    async def _push(ws_id, event):
        pass

    ws.push = _push
    ws.calls = []
    return ws


@pytest.fixture
def session():
    return Session(
        session_id="sess-1",
        user_id="user-1",
        user_ws_id="ws-1",
        agent_version="tether-agent-2.0",
        options={},
    )


@pytest.fixture
def gate_auto_approve(table, mock_ws, session):
    return PermissionGate(
        translation_table=table,
        ws_publisher=mock_ws,
        session=session,
        auto_approve_user_actions=True,
    )


@pytest.fixture
def gate_no_auto(table, mock_ws, session):
    return PermissionGate(
        translation_table=table,
        ws_publisher=mock_ws,
        session=session,
        auto_approve_user_actions=False,
    )


# ---------------------------------------------------------------------------
# 1. BackgroundEntry → always allow
# ---------------------------------------------------------------------------

async def test_background_entry_always_allow(gate_no_auto):
    result = await gate_no_auto.can_use_tool("get_anchors", {}, None)
    assert isinstance(result, PermissionResultAllow)


# ---------------------------------------------------------------------------
# 2. BackgroundHiddenEntry → always allow
# ---------------------------------------------------------------------------

async def test_background_hidden_entry_always_allow(gate_no_auto):
    result = await gate_no_auto.can_use_tool("consult_advisor", {}, None)
    assert isinstance(result, PermissionResultAllow)


# ---------------------------------------------------------------------------
# 3. PassthroughEntry → always allow
# ---------------------------------------------------------------------------

async def test_passthrough_entry_always_allow(gate_no_auto):
    result = await gate_no_auto.can_use_tool(
        "send_status_update", {"text": "hi"}, None
    )
    assert isinstance(result, PermissionResultAllow)


# ---------------------------------------------------------------------------
# 4. UserAction + auto_approve=True → allow, no permission_request pushed
# ---------------------------------------------------------------------------

async def test_user_action_auto_approve_allows(table, session):
    """auto_approve should allow without touching ws at all."""
    pushed = []

    async def _noop_push(ws_id, event):
        pushed.append(event)

    ws = MagicMock()
    ws.push = _noop_push

    gate = PermissionGate(
        translation_table=table,
        ws_publisher=ws,
        session=session,
        auto_approve_user_actions=True,
    )
    result = await gate.can_use_tool("upsert_tasks", {"count": 3, "tasks": []}, None)
    assert isinstance(result, PermissionResultAllow)
    assert pushed == []


# ---------------------------------------------------------------------------
# Helper: run gate concurrently with a blocking ws so we can intercept
# ---------------------------------------------------------------------------

async def _run_with_blocking_ws(table, session, tool_name, args, resolve_value, *, timeout=None):
    """
    Run can_use_tool with a blocking ws.
    Once the gate has pushed the permission_request, resolve the pending future
    with resolve_value (True/False) or leave it (None → rely on natural timeout).
    Returns (result, calls) where calls is the list of push call tuples.
    """
    ws = _make_blocking_ws()
    gate = PermissionGate(
        translation_table=table,
        ws_publisher=ws,
        session=session,
        auto_approve_user_actions=False,
    )

    task = asyncio.create_task(gate.can_use_tool(tool_name, args, None))

    # Wait until the gate has called push (the event is set inside _push).
    await ws.push_event.wait()

    # At this point the gate is suspended inside _push, so permission_pending is populated.
    if resolve_value is not None:
        # Resolve the future first, then unblock push so the gate can proceed.
        pending_copy = dict(session.permission_pending)
        if pending_copy:
            request_id = next(iter(pending_copy))
            fut = pending_copy[request_id]
            fut.set_result(resolve_value)

    # Unblock the ws.push() so the gate continues.
    ws.release_event.set()

    result = await task
    return result, ws.calls


# ---------------------------------------------------------------------------
# 5. UserAction + auto_approve=False → emit permission_request → approve
# ---------------------------------------------------------------------------

async def test_user_action_no_auto_approve_and_user_approves(table, session):
    result, calls = await _run_with_blocking_ws(
        table, session, "upsert_tasks", {"count": 3, "tasks": ["task-1"]},
        resolve_value=True,
    )

    assert isinstance(result, PermissionResultAllow)
    assert len(calls) == 1
    ws_id, event = calls[0]
    assert ws_id == "ws-1"
    assert event["type"] == "permission_request"
    assert event["session_id"] == "sess-1"
    assert "request_id" in event
    assert "summary" in event
    assert "details" in event


# ---------------------------------------------------------------------------
# 6. UserAction + auto_approve=False → timeout → deny
# ---------------------------------------------------------------------------

async def test_user_action_timeout_denies(table, session, monkeypatch):
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 0.01,
    )

    async def _noop_push(ws_id, event):
        pass

    ws = MagicMock()
    ws.push = _noop_push

    gate = PermissionGate(
        translation_table=table,
        ws_publisher=ws,
        session=session,
        auto_approve_user_actions=False,
    )
    result = await gate.can_use_tool("upsert_tasks", {"count": 1, "tasks": []}, None)
    assert isinstance(result, PermissionResultDeny)


# ---------------------------------------------------------------------------
# 7. UserAction + auto_approve=False → future resolved False → deny
# ---------------------------------------------------------------------------

async def test_user_action_denied_by_user(table, session):
    result, _ = await _run_with_blocking_ws(
        table, session, "upsert_tasks", {"count": 1, "tasks": []},
        resolve_value=False,
    )
    assert isinstance(result, PermissionResultDeny)


# ---------------------------------------------------------------------------
# 8. permission_summary interpolation
# ---------------------------------------------------------------------------

async def test_permission_summary_interpolation(table, session):
    _, calls = await _run_with_blocking_ws(
        table, session, "upsert_tasks", {"count": 3, "tasks": []},
        resolve_value=True,
    )
    _, event = calls[0]
    assert event["summary"] == "Update 3 tasks"


# ---------------------------------------------------------------------------
# 9. permission_pending cleaned up after approval/denial/timeout
# ---------------------------------------------------------------------------

async def test_permission_pending_cleaned_up_after_approval(table, session):
    await _run_with_blocking_ws(
        table, session, "upsert_tasks", {"count": 1, "tasks": []},
        resolve_value=True,
    )
    assert session.permission_pending == {}


async def test_permission_pending_cleaned_up_after_denial(table, session):
    await _run_with_blocking_ws(
        table, session, "upsert_tasks", {"count": 1, "tasks": []},
        resolve_value=False,
    )
    assert session.permission_pending == {}


async def test_permission_pending_cleaned_up_after_timeout(table, session, monkeypatch):
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 0.01,
    )

    async def _noop_push(ws_id, event):
        pass

    ws = MagicMock()
    ws.push = _noop_push

    gate = PermissionGate(
        translation_table=table,
        ws_publisher=ws,
        session=session,
        auto_approve_user_actions=False,
    )
    await gate.can_use_tool("upsert_tasks", {"count": 1, "tasks": []}, None)
    assert session.permission_pending == {}
