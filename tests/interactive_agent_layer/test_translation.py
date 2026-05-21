"""Tests for the agent translation table (B2)."""
from __future__ import annotations

import pathlib
import pytest

from interactive_agent_layer.translation import (
    TranslationTable,
    BackgroundEntry,
    BackgroundHiddenEntry,
    PassthroughEntry,
    UserActionEntry,
)


YAML_PATH = (
    pathlib.Path(__file__).parent.parent.parent / "config" / "agent_translations.yaml"
)


@pytest.fixture(scope="module")
def table() -> TranslationTable:
    return TranslationTable.from_yaml(YAML_PATH)


# --- from_yaml loads correctly ---

def test_from_yaml_loads_background(table):
    entry = table.lookup("get_anchors")
    assert isinstance(entry, BackgroundEntry)


def test_from_yaml_loads_background_hidden(table):
    entry = table.lookup("consult_advisor")
    assert isinstance(entry, BackgroundHiddenEntry)


def test_from_yaml_loads_passthrough(table):
    entry = table.lookup("send_status_update")
    assert isinstance(entry, PassthroughEntry)


def test_from_yaml_loads_user_action(table):
    entry = table.lookup("upsert_tasks")
    assert isinstance(entry, UserActionEntry)


# --- Specific field values ---

def test_get_anchors_phrase(table):
    entry = table.lookup("get_anchors")
    assert entry.phrase == "Reading your schedule"


def test_get_plan_phrase(table):
    entry = table.lookup("get_plan")
    assert isinstance(entry, BackgroundEntry)
    assert entry.phrase == "Reading your plan"


def test_consult_advisor_is_background_hidden(table):
    entry = table.lookup("consult_advisor")
    assert isinstance(entry, BackgroundHiddenEntry)
    assert entry.phrase == "Working on it"


def test_upsert_tasks_fields(table):
    entry = table.lookup("upsert_tasks")
    assert isinstance(entry, UserActionEntry)
    assert entry.phrase_short == "Updating tasks"
    assert entry.permission_summary == "Update {count} tasks"
    assert entry.permission_detail_field == "tasks"


def test_delete_tasks_fields(table):
    entry = table.lookup("delete_tasks")
    assert isinstance(entry, UserActionEntry)
    assert entry.phrase_short == "Removing tasks"
    assert entry.permission_detail_field == "operations"


def test_upsert_context_fields(table):
    entry = table.lookup("upsert_context")
    assert isinstance(entry, UserActionEntry)
    assert entry.permission_summary == "Update context: {subject}"
    assert entry.permission_detail_field == "nodes"


# --- Fallback to _unknown ---

def test_unknown_tool_falls_back_to_unknown_entry(table):
    entry = table.lookup("nonexistent_tool_xyz")
    assert isinstance(entry, BackgroundEntry)
    assert entry.phrase == "Working"


# --- Structural: no permission fields on background types ---

def test_background_entry_has_no_permission_summary(table):
    entry = table.lookup("get_anchors")
    assert isinstance(entry, BackgroundEntry)
    assert not hasattr(entry, "permission_summary")
    assert not hasattr(entry, "permission_detail_field")


def test_background_hidden_entry_has_no_permission_summary(table):
    entry = table.lookup("consult_advisor")
    assert isinstance(entry, BackgroundHiddenEntry)
    assert not hasattr(entry, "permission_summary")
    assert not hasattr(entry, "permission_detail_field")


def test_user_action_entry_has_permission_fields(table):
    entry = table.lookup("upsert_tasks")
    assert isinstance(entry, UserActionEntry)
    assert hasattr(entry, "permission_summary")
    assert hasattr(entry, "permission_detail_field")


# --- interpolate_phrase ---

def test_interpolate_search_with_query_arg(table):
    entry = table.lookup("search")
    assert isinstance(entry, BackgroundEntry)
    result = table.interpolate_phrase(entry, {"query": "hello"})
    assert result == "Searching for 'hello'"


def test_interpolate_missing_arg_is_forgiving(table):
    entry = table.lookup("search")
    result = table.interpolate_phrase(entry, {})
    # Missing key should leave literal {query}
    assert "{query}" in result


def test_interpolate_user_action_uses_phrase_short(table):
    entry = table.lookup("upsert_tasks")
    result = table.interpolate_phrase(entry, {"count": 3})
    # Should use phrase_short, not permission_summary
    assert result == "Updating tasks"


def test_interpolate_passthrough_returns_empty_string(table):
    entry = table.lookup("send_status_update")
    assert isinstance(entry, PassthroughEntry)
    result = table.interpolate_phrase(entry, {})
    assert result == ""


def test_interpolate_background_hidden(table):
    entry = table.lookup("consult_advisor")
    result = table.interpolate_phrase(entry, {})
    assert result == "Working on it"
