"""Tests for PermissionGate (TDD — written before implementation)."""
from __future__ import annotations

import asyncio
import pathlib

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
def gate_auto_approve(table, session):
    return PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=asyncio.Queue(),
        auto_approve_user_actions=True,
    )


@pytest.fixture
def gate_no_auto(table, session):
    return PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=asyncio.Queue(),
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
# 4. UserAction + auto_approve=True → allow, no permission_request enqueued
# ---------------------------------------------------------------------------

async def test_user_action_auto_approve_allows(table, session):
    """auto_approve should allow without enqueuing a permission_request."""
    queue: asyncio.Queue = asyncio.Queue()
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=queue,
        auto_approve_user_actions=True,
    )
    result = await gate.can_use_tool("upsert_tasks", {"count": 3, "tasks": []}, None)
    assert isinstance(result, PermissionResultAllow)
    assert queue.empty(), "auto_approve must not enqueue permission_request"


# ---------------------------------------------------------------------------
# Helper: run gate and intercept permission_request via outbound queue
# ---------------------------------------------------------------------------

async def _run_with_queue(
    table, session, tool_name, args, resolve_value, *, timeout=5.0
):
    """
    Run can_use_tool and intercept the permission_request from the outbound queue.

    Once the gate has enqueued the permission_request event, resolve the pending
    future with resolve_value (True/False), or leave it (None → rely on timeout).
    Returns (result, event) where event is the permission_request dict.
    """
    queue: asyncio.Queue = asyncio.Queue()
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=queue,
        auto_approve_user_actions=False,
    )

    task = asyncio.create_task(gate.can_use_tool(tool_name, args, None))

    # Wait until the gate enqueues the permission_request event.
    event = await asyncio.wait_for(queue.get(), timeout=timeout)

    if resolve_value is not None:
        request_id = event["request_id"]
        fut = session.permission_pending.get(request_id)
        if fut is not None and not fut.done():
            fut.set_result(resolve_value)

    result = await task
    return result, event


# ---------------------------------------------------------------------------
# 5. UserAction + auto_approve=False → emit permission_request → approve
# ---------------------------------------------------------------------------

async def test_user_action_no_auto_approve_and_user_approves(table, session):
    result, event = await _run_with_queue(
        table, session, "upsert_tasks", {"count": 3, "tasks": ["task-1"]},
        resolve_value=True,
    )

    assert isinstance(result, PermissionResultAllow)
    assert event["type"] == "permission_request"
    assert event["session_id"] == "sess-1"
    assert "request_id" in event
    assert "kind" in event
    assert "target" in event
    assert "reason_from_bot" in event


# ---------------------------------------------------------------------------
# 6. UserAction + auto_approve=False → timeout → deny
# ---------------------------------------------------------------------------

async def test_user_action_timeout_denies(table, session, monkeypatch):
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 0.01,
    )

    queue: asyncio.Queue = asyncio.Queue()
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=queue,
        auto_approve_user_actions=False,
    )
    # Don't resolve the future — let it time out naturally.
    result = await gate.can_use_tool("upsert_tasks", {"count": 1, "tasks": []}, None)
    assert isinstance(result, PermissionResultDeny)


# ---------------------------------------------------------------------------
# 7. UserAction + auto_approve=False → future resolved False → deny
# ---------------------------------------------------------------------------

async def test_user_action_denied_by_user(table, session):
    result, _ = await _run_with_queue(
        table, session, "upsert_tasks", {"count": 1, "tasks": []},
        resolve_value=False,
    )
    assert isinstance(result, PermissionResultDeny)


# ---------------------------------------------------------------------------
# 8. target interpolation (was: permission_summary interpolation)
# ---------------------------------------------------------------------------

async def test_permission_target_interpolation(table, session):
    _, event = await _run_with_queue(
        table, session, "upsert_tasks", {"count": 3, "tasks": []},
        resolve_value=True,
    )
    assert event["target"] == "Update 3 tasks"


# ---------------------------------------------------------------------------
# 9. permission_pending cleaned up after approval/denial/timeout
# ---------------------------------------------------------------------------

async def test_permission_pending_cleaned_up_after_approval(table, session):
    await _run_with_queue(
        table, session, "upsert_tasks", {"count": 1, "tasks": []},
        resolve_value=True,
    )
    assert session.permission_pending == {}


async def test_permission_pending_cleaned_up_after_denial(table, session):
    await _run_with_queue(
        table, session, "upsert_tasks", {"count": 1, "tasks": []},
        resolve_value=False,
    )
    assert session.permission_pending == {}


async def test_permission_pending_cleaned_up_after_timeout(table, session, monkeypatch):
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 0.01,
    )

    queue: asyncio.Queue = asyncio.Queue()
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=queue,
        auto_approve_user_actions=False,
    )
    await gate.can_use_tool("upsert_tasks", {"count": 1, "tasks": []}, None)
    assert session.permission_pending == {}
