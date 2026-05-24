"""Regression tests — Pool._build_sdk_options must pass all dataclass fields through.

ROOT CAUSE OF THE 15s WARM-SPAWN TIMEOUT (discovered via the diagnostic
logging in this PR):

``_build_sdk_options`` filtered options keys against
``dir(ClaudeAgentOptions)``, but ``dir()`` on a dataclass class does NOT
include fields whose declaration uses ``default_factory``.  Eight fields
were silently dropped:

  add_dirs, allowed_tools, betas, disallowed_tools, env, extra_args,
  mcp_servers, plugins

Most importantly, **env was dropped**, which meant the OAuth token
injected by PR #419 never reached the subprocess.  The CLI then sat at
its OAuth handshake for 15 s, hit the connect_timeout, and the warm spawn
failed.  PR #421's spawn guard (which checks ``options['env']`` before
``_build_sdk_options`` runs) saw the token and allowed the spawn — but
the token was stripped one stack frame later.

Fix: use ``dataclasses.fields()`` instead of ``dir()`` to enumerate the
real dataclass fields.

These tests pin the contract so the bug can't reappear: every dataclass
field on ``ClaudeAgentOptions`` whose presence matters at runtime must
pass through ``_build_sdk_options`` unchanged.
"""
from __future__ import annotations

import dataclasses

import pytest
from claude_agent_sdk import ClaudeAgentOptions

from agent_pool_manager.pool import Pool


# ---------------------------------------------------------------------------
# The critical regression: env passthrough
# ---------------------------------------------------------------------------

def test_build_sdk_options_passes_env_through():
    """The OAuth token in env MUST reach ClaudeAgentOptions.

    This is the bug that caused the 15 s warm-spawn timeout in production.
    PR #419 injected the token correctly, PR #421's spawn guard saw it,
    but ``_build_sdk_options`` then stripped it because ``dir()`` doesn't
    list fields with default_factory.
    """
    env = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-test-token-xyz"}
    sdk_options = Pool._build_sdk_options({"env": env})
    assert sdk_options.env == env, (
        "env must pass through _build_sdk_options — without it the OAuth "
        "token never reaches the subprocess and connect() hangs 15s."
    )


# ---------------------------------------------------------------------------
# The other 7 silently-dropped fields
# ---------------------------------------------------------------------------

def test_build_sdk_options_passes_mcp_servers_through():
    """mcp_servers (whether list or dict form) must reach the SDK."""
    sdk_options = Pool._build_sdk_options({"mcp_servers": ["tether"]})
    assert sdk_options.mcp_servers == ["tether"]


def test_build_sdk_options_passes_allowed_tools_through():
    """allowed_tools must reach the SDK — controls what the agent can call."""
    tools = ["upsert_tasks", "read_context"]
    sdk_options = Pool._build_sdk_options({"allowed_tools": tools})
    assert sdk_options.allowed_tools == tools


def test_build_sdk_options_passes_disallowed_tools_through():
    """disallowed_tools must reach the SDK — security-relevant."""
    sdk_options = Pool._build_sdk_options({"disallowed_tools": ["bash"]})
    assert sdk_options.disallowed_tools == ["bash"]


def test_build_sdk_options_passes_extra_args_through():
    """extra_args must reach the SDK — used for CLI flag passthrough."""
    sdk_options = Pool._build_sdk_options({"extra_args": {"debug-to-stderr": None}})
    assert sdk_options.extra_args == {"debug-to-stderr": None}


def test_build_sdk_options_passes_add_dirs_through():
    """add_dirs must reach the SDK — workspace directories."""
    sdk_options = Pool._build_sdk_options({"add_dirs": ["/tmp/work"]})
    assert sdk_options.add_dirs == ["/tmp/work"]


def test_build_sdk_options_passes_betas_through():
    """betas must reach the SDK — controls beta features."""
    sdk_options = Pool._build_sdk_options({"betas": ["some-beta"]})
    assert sdk_options.betas == ["some-beta"]


def test_build_sdk_options_passes_plugins_through():
    """plugins must reach the SDK — plugin config."""
    # plugins is a list of TypedDict; we just check the list is passed through.
    plugin = {"type": "local", "path": "/tmp/plug"}
    sdk_options = Pool._build_sdk_options({"plugins": [plugin]})
    assert sdk_options.plugins == [plugin]


# ---------------------------------------------------------------------------
# Defence-in-depth: prove the enumeration uses dataclasses.fields(), not dir().
# ---------------------------------------------------------------------------

def test_build_sdk_options_enumerates_via_dataclasses_fields():
    """All dataclass fields with default_factory must be enumerable.

    If a future refactor swaps back to ``dir()``-based field discovery,
    this test will catch it: the eight default_factory fields would
    silently disappear again.
    """
    declared_fields = {f.name for f in dataclasses.fields(ClaudeAgentOptions)}
    # The eight fields that used to be silently dropped
    must_be_enumerable = {
        "add_dirs", "allowed_tools", "betas", "disallowed_tools",
        "env", "extra_args", "mcp_servers", "plugins",
    }
    assert must_be_enumerable.issubset(declared_fields), (
        "ClaudeAgentOptions field set changed — update this regression test"
    )

    # Round-trip every default_factory field — pass a sentinel value and
    # confirm it survives _build_sdk_options.
    for name in must_be_enumerable:
        if name in {"betas", "plugins", "allowed_tools", "disallowed_tools", "add_dirs"}:
            value = []
        elif name in {"env", "extra_args", "mcp_servers"}:
            value = {}
        else:
            value = None
        sdk_options = Pool._build_sdk_options({name: value})
        assert getattr(sdk_options, name) == value, (
            f"Field {name!r} did not survive _build_sdk_options — "
            f"dataclasses.fields() enumeration broken."
        )


# ---------------------------------------------------------------------------
# Unknown keys still get dropped.
# ---------------------------------------------------------------------------

def test_build_sdk_options_drops_unknown_keys():
    """Unknown keys must still be silently dropped — the fix only adds back
    the dataclass fields, not arbitrary keys."""
    # This must not raise (i.e. the unknown key was filtered out before
    # being passed to ClaudeAgentOptions(...)).
    sdk_options = Pool._build_sdk_options({
        "model": "claude-haiku-4-5",
        "_some_internal_unknown_key": "should be dropped",
        "nonsense": 123,
    })
    assert sdk_options.model == "claude-haiku-4-5"
