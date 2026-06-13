"""Tests for read_context scope gating via PermissionGate (TDD — written before implementation)."""
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
        session_id="sess-scope",
        user_id="user-1",
        user_ws_id="ws-1",
        agent_version="tether-agent-2.0",
        options={
            "scope_source_node_id": "node-source",
            "scope_radius": 2,
        },
    )


def _make_gate(
    table,
    session,
    hop_fn=None,
    scope_mode="tree_distance",
    resolve_path_fn=None,
    *,
    auto_approve=False,
):
    return PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=asyncio.Queue(),
        auto_approve_user_actions=auto_approve,
        scope_source_node_id=session.options.get("scope_source_node_id"),
        scope_radius=session.options.get("scope_radius"),
        scope_mode=scope_mode,
        hop_distance_fn=hop_fn,
        resolve_node_path_fn=resolve_path_fn,
    )


async def _run_scope_check(table, session, args, hop_fn, resolve_path_fn=None):
    """Run can_use_tool for read_context, intercept the permission_request event.

    Returns (task, event, session) — caller must resolve the future before awaiting task.
    """
    queue: asyncio.Queue = asyncio.Queue()
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=queue,
        auto_approve_user_actions=False,
        scope_source_node_id=session.options.get("scope_source_node_id"),
        scope_radius=session.options.get("scope_radius"),
        hop_distance_fn=hop_fn,
        resolve_node_path_fn=resolve_path_fn,
    )
    task = asyncio.create_task(gate.can_use_tool("read_context", args, None))
    event = await asyncio.wait_for(queue.get(), timeout=5.0)
    return task, event


# ---------------------------------------------------------------------------
# A: No scope configured → no gating
# ---------------------------------------------------------------------------


async def test_read_context_no_scope_source_always_allow(table, session):
    """When scope_source_node_id is not set, read_context is not scope-gated."""
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=asyncio.Queue(),
        auto_approve_user_actions=False,
        # scope params intentionally omitted
    )
    result = await gate.can_use_tool("read_context", {"node_ids": ["node-far-away"]}, None)
    assert isinstance(result, PermissionResultAllow)


async def test_read_context_hop_fn_none_always_allow(table, session):
    """When hop_distance_fn is None (even if source is set), gate is inactive."""
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=asyncio.Queue(),
        auto_approve_user_actions=False,
        scope_source_node_id="node-source",
        scope_radius=2,
        hop_distance_fn=None,
    )
    result = await gate.can_use_tool("read_context", {"node_ids": ["node-far-away"]}, None)
    assert isinstance(result, PermissionResultAllow)


async def test_read_context_no_targets_always_allow(table, session):
    """No paths and no node_ids → allow (root read; agent browsing from root)."""

    async def hop_fn(from_id, to_id):
        raise AssertionError("hop_fn must not be called with no targets")

    gate = _make_gate(table, session, hop_fn)
    result = await gate.can_use_tool("read_context", {}, None)
    assert isinstance(result, PermissionResultAllow)


# ---------------------------------------------------------------------------
# C: In-scope targets → allow
# ---------------------------------------------------------------------------


async def test_read_context_in_scope_node_id_allows(table, session):
    """Distance ≤ M → allow without prompting."""

    async def hop_fn(from_id, to_id):
        return 1  # within radius 2

    gate = _make_gate(table, session, hop_fn)
    result = await gate.can_use_tool("read_context", {"node_ids": ["node-child"]}, None)
    assert isinstance(result, PermissionResultAllow)


async def test_read_context_self_node_allows(table, session):
    """Reading the source node itself (distance 0) → allow."""

    async def hop_fn(from_id, to_id):
        return 0

    gate = _make_gate(table, session, hop_fn)
    result = await gate.can_use_tool("read_context", {"node_ids": ["node-source"]}, None)
    assert isinstance(result, PermissionResultAllow)


async def test_read_context_all_targets_in_scope_allows(table, session):
    """All node_ids within scope → allow without prompting."""

    async def hop_fn(from_id, to_id):
        return 2  # exactly at M boundary — in scope

    gate = _make_gate(table, session, hop_fn)
    result = await gate.can_use_tool(
        "read_context", {"node_ids": ["node-a", "node-b"]}, None
    )
    assert isinstance(result, PermissionResultAllow)


# ---------------------------------------------------------------------------
# C: Out-of-scope targets → emit permission_request
# ---------------------------------------------------------------------------


async def test_read_context_out_of_scope_emits_permission_request(table, session):
    """Distance > M → permission_request with kind='read_out_of_scope' emitted."""

    async def hop_fn(from_id, to_id):
        return 5  # exceeds radius 2

    task, event = await _run_scope_check(
        table, session, {"node_ids": ["node-distant"]}, hop_fn
    )
    request_id = event["request_id"]
    fut = session.permission_pending.get(request_id)
    if fut and not fut.done():
        fut.set_result(True)
    result = await task

    assert event["type"] == "permission_request"
    assert event.get("kind") == "read_out_of_scope"
    assert "node-distant" in str(event.get("target", ""))
    assert isinstance(result, PermissionResultAllow)


async def test_read_context_out_of_scope_user_denies(table, session):
    """User denies the scope prompt → PermissionResultDeny."""

    async def hop_fn(from_id, to_id):
        return 5

    task, event = await _run_scope_check(
        table, session, {"node_ids": ["node-distant"]}, hop_fn
    )
    request_id = event["request_id"]
    fut = session.permission_pending.get(request_id)
    if fut and not fut.done():
        fut.set_result(False)
    result = await task

    assert isinstance(result, PermissionResultDeny)


async def test_read_context_none_distance_treated_as_out_of_scope(table, session):
    """None from hop_fn (unrelated/no-path nodes) → treated as out-of-scope."""

    async def hop_fn(from_id, to_id):
        return None  # unrelated trees

    task, event = await _run_scope_check(
        table, session, {"node_ids": ["node-unrelated"]}, hop_fn
    )
    request_id = event["request_id"]
    fut = session.permission_pending.get(request_id)
    if fut and not fut.done():
        fut.set_result(True)
    await task

    assert event["type"] == "permission_request"
    assert event.get("kind") == "read_out_of_scope"


async def test_read_context_first_offender_is_reported_in_target(table, session):
    """Multiple node_ids: first out-of-scope target reported in event.target."""

    async def hop_fn(from_id, to_id):
        return 1 if to_id == "node-close" else 5

    task, event = await _run_scope_check(
        table, session,
        {"node_ids": ["node-close", "node-distant"]},
        hop_fn,
    )
    request_id = event["request_id"]
    fut = session.permission_pending.get(request_id)
    if fut and not fut.done():
        fut.set_result(True)
    await task

    assert event.get("kind") == "read_out_of_scope"
    assert "node-distant" in str(event.get("target", ""))


# ---------------------------------------------------------------------------
# C: Path targets → resolved then gated
# ---------------------------------------------------------------------------


async def test_read_context_path_resolved_and_gated(table, session):
    """Path arg is resolved to node_id then scope-checked."""

    async def hop_fn(from_id, to_id):
        return 5  # out of scope

    async def resolve_path(path):
        return "node-resolved-from-path"

    task, event = await _run_scope_check(
        table, session,
        {"paths": ["Projects/OutOfScope"]},
        hop_fn,
        resolve_path_fn=resolve_path,
    )
    request_id = event["request_id"]
    fut = session.permission_pending.get(request_id)
    if fut and not fut.done():
        fut.set_result(True)
    await task

    assert event.get("kind") == "read_out_of_scope"


async def test_read_context_unresolvable_path_is_out_of_scope(table, session):
    """Path that resolves to None (not found) → treat as out-of-scope."""

    async def hop_fn(from_id, to_id):
        return 1  # would be in-scope if resolved

    async def resolve_path(path):
        return None  # path not found

    task, event = await _run_scope_check(
        table, session,
        {"paths": ["NonExistent/Ghost"]},
        hop_fn,
        resolve_path_fn=resolve_path,
    )
    request_id = event["request_id"]
    fut = session.permission_pending.get(request_id)
    if fut and not fut.done():
        fut.set_result(True)
    await task

    assert event.get("kind") == "read_out_of_scope"


async def test_read_context_path_in_scope_allows(table, session):
    """Path that resolves to in-scope node → allow."""

    async def hop_fn(from_id, to_id):
        return 1  # in scope

    async def resolve_path(path):
        return "node-resolved"

    gate = _make_gate(table, session, hop_fn, resolve_path_fn=resolve_path)
    result = await gate.can_use_tool(
        "read_context", {"paths": ["Projects/InScope"]}, None
    )
    assert isinstance(result, PermissionResultAllow)


# ---------------------------------------------------------------------------
# Scope check does not affect other tools
# ---------------------------------------------------------------------------


async def test_non_read_context_tools_unaffected_by_scope(table, session):
    """Scope check applies only to read_context; other tools dispatch normally."""

    async def hop_fn(from_id, to_id):
        raise AssertionError("hop_fn must not be called for non-read_context tools")

    gate = _make_gate(table, session, hop_fn)
    # get_anchors is background → always allow
    result = await gate.can_use_tool("get_anchors", {}, None)
    assert isinstance(result, PermissionResultAllow)


# ---------------------------------------------------------------------------
# permission_pending cleanup after scope gate
# ---------------------------------------------------------------------------


async def test_scope_gate_pending_cleaned_up_after_approve(table, session):
    """permission_pending dict is clean after scope approval."""

    async def hop_fn(from_id, to_id):
        return 5

    task, event = await _run_scope_check(
        table, session, {"node_ids": ["node-far"]}, hop_fn
    )
    request_id = event["request_id"]
    fut = session.permission_pending.get(request_id)
    if fut and not fut.done():
        fut.set_result(True)
    await task

    assert session.permission_pending == {}


async def test_scope_gate_timeout_denies(table, session, monkeypatch):
    """Timeout while scope gate is pending → PermissionResultDeny."""
    monkeypatch.setattr(
        "interactive_agent_layer.permissions.get_permission_timeout",
        lambda: 0.01,
    )

    async def hop_fn(from_id, to_id):
        return 5  # out of scope — gate will await

    queue: asyncio.Queue = asyncio.Queue()
    gate = PermissionGate(
        translation_table=table,
        session=session,
        outbound_events=queue,
        auto_approve_user_actions=False,
        scope_source_node_id="node-source",
        scope_radius=2,
        hop_distance_fn=hop_fn,
    )
    result = await gate.can_use_tool("read_context", {"node_ids": ["node-far"]}, None)
    assert isinstance(result, PermissionResultDeny)
