"""Tests for write_node_memory v2 hard enforcement of read-before-write.

All tests mock the DB layer — no Postgres required.

Enforcement rules (v2):
  1. conversation_id is required — returns error if absent.
  2. A read of the target node must exist in node_read_log for the given
     conversation_id before any write is allowed (additive, edit, delete).
  3. If both requirements are met the write proceeds normally.
"""
from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, patch

import pytest

NODE_ID = "aaaaaaaa-0000-0000-0000-000000000001"
CONV_ID = "bbbbbbbb-0000-0000-0000-000000000002"

PATCH_TARGETS = [
    "db.pg_queries.node_memory.has_read_node_in_conversation",
    "db.pg_queries.node_memory.log_node_read",
    "db.pg_queries.sections.get_section",
    "db.pg_queries.sections.upsert_section",
    "db.pg_queries.sections.append_section",
    "db.pg_queries.sections.delete_section",
]


@pytest.fixture
def conn():
    return AsyncMock()


def _make_mocks(has_read: bool = True) -> dict:
    mocks = {t.split(".")[-1]: AsyncMock() for t in PATCH_TARGETS}
    mocks["has_read_node_in_conversation"].return_value = has_read
    mocks["get_section"].return_value = {"id": "sec-1", "body": "existing"}
    return mocks


@contextlib.contextmanager
def _patch_all(mocks: dict):
    with contextlib.ExitStack() as stack:
        for t in PATCH_TARGETS:
            key = t.split(".")[-1]
            stack.enter_context(patch(t, mocks[key]))
        yield mocks


async def _run(conn, mocks, **kwargs):
    with _patch_all(mocks):
        from tether_mcp.tools.write_node_memory import execute_write_node_memory
        return await execute_write_node_memory(conn, **kwargs)


# ---------------------------------------------------------------------------
# A-1: conversation_id required
# ---------------------------------------------------------------------------

class TestConversationIdRequired:
    @pytest.mark.asyncio
    async def test_additive_without_conversation_id_returns_error(self, conn):
        mocks = _make_mocks()
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="hello",
            mode="additive",
            conversation_id=None,
        )
        assert result.get("error") == "conversation_id_required"
        mocks["append_section"].assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_without_conversation_id_returns_error(self, conn):
        mocks = _make_mocks()
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="hello",
            mode="edit",
            conversation_id=None,
        )
        assert result.get("error") == "conversation_id_required"
        mocks["upsert_section"].assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_without_conversation_id_returns_error(self, conn):
        mocks = _make_mocks()
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="",
            mode="delete",
            conversation_id=None,
        )
        assert result.get("error") == "conversation_id_required"
        mocks["delete_section"].assert_not_called()


# ---------------------------------------------------------------------------
# A-2: read-before-write enforcement
# ---------------------------------------------------------------------------

class TestReadBeforeWriteEnforcement:
    @pytest.mark.asyncio
    async def test_additive_without_prior_read_returns_error(self, conn):
        mocks = _make_mocks(has_read=False)
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="hello",
            mode="additive",
            conversation_id=CONV_ID,
        )
        assert result.get("error") == "read_before_write_required"
        mocks["append_section"].assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_without_prior_read_returns_error(self, conn):
        mocks = _make_mocks(has_read=False)
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="hello",
            mode="edit",
            conversation_id=CONV_ID,
        )
        assert result.get("error") == "read_before_write_required"
        mocks["upsert_section"].assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_without_prior_read_returns_error(self, conn):
        mocks = _make_mocks(has_read=False)
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="",
            mode="delete",
            conversation_id=CONV_ID,
        )
        assert result.get("error") == "read_before_write_required"
        mocks["delete_section"].assert_not_called()

    @pytest.mark.asyncio
    async def test_has_read_check_uses_correct_args(self, conn):
        """has_read_node_in_conversation is called with (conn, node_id, conversation_id),
        plus the optional RLS-hardening user_id kwarg (None unless the caller binds it)."""
        mocks = _make_mocks(has_read=False)
        await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="hi",
            mode="edit",
            conversation_id=CONV_ID,
        )
        mocks["has_read_node_in_conversation"].assert_called_once_with(
            conn, NODE_ID, CONV_ID, user_id=None
        )


# ---------------------------------------------------------------------------
# A-3: success path — read logged before write
# ---------------------------------------------------------------------------

class TestWriteSucceedsAfterRead:
    @pytest.mark.asyncio
    async def test_additive_with_prior_read_succeeds(self, conn):
        mocks = _make_mocks(has_read=True)
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="hello",
            mode="additive",
            conversation_id=CONV_ID,
        )
        assert result.get("status") == "ok"
        assert result.get("mode") == "additive"
        mocks["append_section"].assert_called_once()

    @pytest.mark.asyncio
    async def test_edit_with_prior_read_succeeds(self, conn):
        mocks = _make_mocks(has_read=True)
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="hello",
            mode="edit",
            conversation_id=CONV_ID,
        )
        assert result.get("status") == "ok"
        assert result.get("mode") == "edit"
        mocks["upsert_section"].assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_with_prior_read_succeeds(self, conn):
        mocks = _make_mocks(has_read=True)
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="",
            mode="delete",
            conversation_id=CONV_ID,
        )
        assert result.get("status") == "ok"
        assert result.get("mode") == "delete"
        mocks["delete_section"].assert_called_once()

    @pytest.mark.asyncio
    async def test_no_warning_in_success_response(self, conn):
        """v2 success path must not include the advisory warning field."""
        mocks = _make_mocks(has_read=True)
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="hello",
            mode="edit",
            conversation_id=CONV_ID,
        )
        assert "warning" not in result


# ---------------------------------------------------------------------------
# A-4: invalid mode still errors before read check
# ---------------------------------------------------------------------------

class TestInvalidMode:
    @pytest.mark.asyncio
    async def test_invalid_mode_returns_error_regardless_of_conversation_id(self, conn):
        mocks = _make_mocks()
        result = await _run(
            conn, mocks,
            node_id=NODE_ID, title="notes", data_type="text", value="hi",
            mode="INVALID",
            conversation_id=CONV_ID,
        )
        assert result.get("error") == "invalid_mode"
        mocks["has_read_node_in_conversation"].assert_not_called()
