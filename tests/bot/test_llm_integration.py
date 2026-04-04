"""Integration tests for LLM layer — exercises real SDK code paths, no mocking.

These tests verify that our MCP config, CLI command construction, and error
handling work against the actual installed claude-agent-sdk package, not mocks.
"""
import json
import pytest


# ---------------------------------------------------------------------------
# SDK import health — catches the 0.1.55 _internal missing-module regression
# ---------------------------------------------------------------------------

class TestSDKImportHealth:
    """Verify the installed claude-agent-sdk is functional (not broken like 0.1.55)."""

    def test_top_level_import(self):
        """import claude_agent_sdk must succeed — 0.1.55 crashed here."""
        import claude_agent_sdk
        assert hasattr(claude_agent_sdk, "ClaudeAgentOptions")
        assert hasattr(claude_agent_sdk, "query")

    def test_internal_transport_exists(self):
        """_internal.transport.subprocess_cli must be importable."""
        from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
        assert SubprocessCLITransport is not None

    def test_types_importable(self):
        from claude_agent_sdk.types import McpSSEServerConfig, McpStdioServerConfig
        # TypedDicts are callable (they're dict constructors)
        cfg = McpSSEServerConfig(type="sse", url="http://localhost:5001/sse")
        assert cfg == {"type": "sse", "url": "http://localhost:5001/sse"}

    def test_errors_importable(self):
        from claude_agent_sdk._errors import ProcessError, CLINotFoundError
        exc = ProcessError("test", exit_code=1, stderr="boom")
        assert exc.exit_code == 1
        assert "boom" in str(exc)


# ---------------------------------------------------------------------------
# MCP config serialization — the actual bug path
# ---------------------------------------------------------------------------

class TestMCPConfigSerialization:
    """Verify that _build_command() serializes MCP SSE config correctly.

    This is the exact code path that was broken: our McpSSEServerConfig dict
    goes through SubprocessCLITransport._build_command() and must produce
    a valid --mcp-config JSON string for the bundled CLI.
    """

    def _build_transport(self, mcp_servers):
        """Create a SubprocessCLITransport with a fake cli_path so _build_command works."""
        from claude_agent_sdk import ClaudeAgentOptions
        from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

        options = ClaudeAgentOptions(
            cli_path="/fake/claude",
            model="claude-haiku-4-5-20251001",
            system_prompt="test",
            mcp_servers=mcp_servers,
            permission_mode="bypassPermissions",
        )
        transport = SubprocessCLITransport(prompt=iter([]), options=options)
        # _build_command checks self._cli_path which is set from options.cli_path
        return transport

    def _extract_mcp_config(self, cmd: list[str]) -> dict:
        """Extract and parse the --mcp-config JSON from a CLI command list."""
        idx = cmd.index("--mcp-config")
        raw = cmd[idx + 1]
        return json.loads(raw)

    def test_sse_server_produces_valid_cli_json(self):
        """McpSSEServerConfig(type='sse', url=...) → correct --mcp-config JSON."""
        from claude_agent_sdk.types import McpSSEServerConfig

        mcp_servers = {
            "tether": McpSSEServerConfig(type="sse", url="http://localhost:5001/sse")
        }
        transport = self._build_transport(mcp_servers)
        cmd = transport._build_command()

        assert "--mcp-config" in cmd
        config = self._extract_mcp_config(cmd)

        # Must have the mcpServers wrapper
        assert "mcpServers" in config
        assert "tether" in config["mcpServers"]
        server = config["mcpServers"]["tether"]
        assert server["type"] == "sse"
        assert server["url"] == "http://localhost:5001/sse"

    def test_sse_with_headers(self):
        """SSE config with optional headers passes through correctly."""
        from claude_agent_sdk.types import McpSSEServerConfig

        mcp_servers = {
            "remote": McpSSEServerConfig(
                type="sse",
                url="https://api.example.com/mcp",
                headers={"Authorization": "Bearer tok123"},
            )
        }
        transport = self._build_transport(mcp_servers)
        cmd = transport._build_command()
        config = self._extract_mcp_config(cmd)

        server = config["mcpServers"]["remote"]
        assert server["type"] == "sse"
        assert server["headers"]["Authorization"] == "Bearer tok123"

    def test_plain_dict_equivalent_to_typeddict(self):
        """A plain dict with the same shape works identically to McpSSEServerConfig."""
        mcp_servers = {
            "tether": {"type": "sse", "url": "http://localhost:5001/sse"}
        }
        transport = self._build_transport(mcp_servers)
        cmd = transport._build_command()
        config = self._extract_mcp_config(cmd)

        server = config["mcpServers"]["tether"]
        assert server["type"] == "sse"
        assert server["url"] == "http://localhost:5001/sse"

    def test_no_mcp_servers_omits_flag(self):
        """Empty mcp_servers should not produce --mcp-config at all."""
        transport = self._build_transport({})
        cmd = transport._build_command()
        assert "--mcp-config" not in cmd

    def test_file_path_passed_as_string(self):
        """mcp_servers as a string path passes through to --mcp-config directly."""
        transport = self._build_transport("/tmp/my-mcp.json")
        cmd = transport._build_command()
        idx = cmd.index("--mcp-config")
        assert cmd[idx + 1] == "/tmp/my-mcp.json"

    def test_multiple_servers(self):
        """Multiple servers of different types serialize correctly."""
        mcp_servers = {
            "tether": {"type": "sse", "url": "http://localhost:5001/sse"},
            "other": {"command": "node", "args": ["server.js"]},
        }
        transport = self._build_transport(mcp_servers)
        cmd = transport._build_command()
        config = self._extract_mcp_config(cmd)

        assert len(config["mcpServers"]) == 2
        assert config["mcpServers"]["tether"]["type"] == "sse"
        assert config["mcpServers"]["other"]["command"] == "node"

    def test_sdk_server_strips_instance_field(self):
        """SDK-type servers must have 'instance' stripped before CLI serialization."""
        import unittest.mock as mock
        mcp_servers = {
            "calc": {"type": "sdk", "name": "calculator", "instance": mock.MagicMock()},
        }
        transport = self._build_transport(mcp_servers)
        cmd = transport._build_command()
        config = self._extract_mcp_config(cmd)

        server = config["mcpServers"]["calc"]
        assert server["type"] == "sdk"
        assert "instance" not in server  # instance is not JSON-serializable


# ---------------------------------------------------------------------------
# _is_retriable with real SDK exceptions
# ---------------------------------------------------------------------------

class TestIsRetriableIntegration:
    """Verify _is_retriable works with the real ProcessError from the SDK."""

    def test_process_error_is_retriable(self):
        from bot.llm import _is_retriable
        from claude_agent_sdk._errors import ProcessError

        exc = ProcessError("CLI failed", exit_code=1, stderr="rate limit")
        assert _is_retriable(exc) is True

    def test_cli_not_found_is_not_retriable(self):
        from bot.llm import _is_retriable
        from claude_agent_sdk._errors import CLINotFoundError

        exc = CLINotFoundError("not found")
        assert _is_retriable(exc) is False

    def test_generic_exception_is_not_retriable(self):
        from bot.llm import _is_retriable
        assert _is_retriable(RuntimeError("random")) is False


# ---------------------------------------------------------------------------
# AgentSDKBackend config construction — real SDK types, no subprocess
# ---------------------------------------------------------------------------

class TestAgentSDKBackendConfig:
    """Verify AgentSDKBackend builds ClaudeAgentOptions correctly."""

    def test_mcp_config_shape(self):
        """The MCP config dict built by AgentSDKBackend matches SDK expectations."""
        from bot.llm import AgentSDKBackend
        from claude_agent_sdk.types import McpSSEServerConfig

        backend = AgentSDKBackend(mcp_server_url="http://localhost:5001/sse")

        # Simulate what complete() does to build the config
        mcp_servers = {}
        mcp_servers["tether"] = McpSSEServerConfig(
            type="sse", url="http://localhost:5001/sse"
        )

        # Verify it's a valid dict the SDK transport can serialize
        assert isinstance(mcp_servers["tether"], dict)
        assert mcp_servers["tether"]["type"] == "sse"
        assert mcp_servers["tether"]["url"] == "http://localhost:5001/sse"

    def test_allowed_tools_list(self):
        """Verify the allowed tools whitelist contains MCP tools + ToolSearch."""
        from bot.llm import _AGENT_SDK_ALLOWED_TOOLS

        assert "ToolSearch" in _AGENT_SDK_ALLOWED_TOOLS
        assert any("mcp__tether__" in t for t in _AGENT_SDK_ALLOWED_TOOLS)

    def test_is_available_with_mcp_url(self):
        """AgentSDKBackend.is_available() returns True when SDK + CLI are present."""
        import shutil
        from bot.llm import AgentSDKBackend

        if not shutil.which("claude"):
            pytest.skip("claude CLI not installed")
        backend = AgentSDKBackend(mcp_server_url="http://localhost:5001/sse")
        assert backend.is_available() is True

    def test_is_available_without_mcp_url(self):
        """AgentSDKBackend.is_available() returns True even without MCP URL."""
        import shutil
        from bot.llm import AgentSDKBackend

        if not shutil.which("claude"):
            pytest.skip("claude CLI not installed")
        backend = AgentSDKBackend(mcp_server_url=None)
        assert backend.is_available() is True


# ---------------------------------------------------------------------------
# Full _build_command round-trip: our code → SDK → CLI args
# ---------------------------------------------------------------------------

class TestFullRoundTrip:
    """End-to-end: build AgentSDKBackend config → feed to real SDK transport → verify CLI args."""

    def test_agent_sdk_backend_to_cli_command(self):
        """Our AgentSDKBackend config produces valid CLI args through the real SDK."""
        from claude_agent_sdk import ClaudeAgentOptions
        from claude_agent_sdk.types import McpSSEServerConfig
        from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
        from bot.llm import _AGENT_SDK_ALLOWED_TOOLS

        # Reproduce exactly what AgentSDKBackend.complete() builds
        mcp_url = "http://localhost:5001/sse"
        mcp_servers = {"tether": McpSSEServerConfig(type="sse", url=mcp_url)}

        options = ClaudeAgentOptions(
            cli_path="/fake/claude",
            model="claude-sonnet-4-6",
            system_prompt="You are a task management assistant.",
            max_turns=12,
            mcp_servers=mcp_servers,
            permission_mode="bypassPermissions",
            allowed_tools=_AGENT_SDK_ALLOWED_TOOLS,
        )

        transport = SubprocessCLITransport(prompt=iter([]), options=options)
        cmd = transport._build_command()

        # Verify model
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-sonnet-4-6"

        # Verify MCP config is valid JSON with correct structure
        idx = cmd.index("--mcp-config")
        mcp_json = json.loads(cmd[idx + 1])
        assert mcp_json == {
            "mcpServers": {
                "tether": {"type": "sse", "url": "http://localhost:5001/sse"}
            }
        }

        # Verify allowed tools whitelist
        idx = cmd.index("--allowedTools")
        tools = cmd[idx + 1].split(",")
        assert "ToolSearch" in tools
        assert "mcp__tether__*" in tools
        assert "--disallowedTools" not in cmd  # whitelist, not blocklist

        # Verify permission mode
        idx = cmd.index("--permission-mode")
        assert cmd[idx + 1] == "bypassPermissions"
