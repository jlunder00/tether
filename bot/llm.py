"""LLM abstraction layer for Tether v3.

Provides a vendor-agnostic interface for LLM completions.
LLMRouter.complete(role=...) resolves the role to a (vendor, model) pair,
builds a fallback chain, and tries each backend in order.

Fallback chains:
  Anthropic: AnthropicBackend (NATIVE) → AgentSDKBackend (MCP) → PipelineBackend (STRUCTURED)
  Other vendors: direct backend only — failures propagate

ToolMode captures what each tier can do:
  NATIVE    — tool_calls returned in LLMResponse; callers run tool loop
  MCP       — claude binary calls tether MCP tools internally; tool_calls=[] always
  STRUCTURED — no tools; tool names injected into system prompt for structured output
"""
import asyncio
import os
import json
import time
import subprocess
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto

logger = logging.getLogger(__name__)

_DEFAULT_CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")

# Default role → (vendor, model) assignments. Overridable via roles_config in LLMRouter.
_DEFAULT_ROLES: dict[str, dict[str, str]] = {
    "main_agent":    {"vendor": "anthropic", "model": "claude-sonnet-4-6"},
    "classifier":    {"vendor": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "subagent":      {"vendor": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "memory":        {"vendor": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "summarizer":    {"vendor": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "beacon_triage": {"vendor": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "beacon_action": {"vendor": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "dream":         {"vendor": "anthropic", "model": "claude-haiku-4-5-20251001"},
}

# Claude Code native tools to disable in AgentSDKBackend (only tether MCP tools should be usable).
_CLAUDE_CODE_NATIVE_TOOLS = [
    "bash", "computer", "read", "write", "edit", "glob", "grep",
    "ls", "agent", "todo_write", "web_fetch", "web_search",
]


class ToolMode(Enum):
    NATIVE     = auto()  # Direct SDK — tool_calls in LLMResponse; caller runs the loop
    MCP        = auto()  # Agent SDK — tools via MCP internally; tool_calls=[] always
    STRUCTURED = auto()  # Pipeline — no tools; tool names injected into system prompt


def _add_structured_output_hint(system: str | list[str], tools: list[dict] | None) -> str:
    """Inject tool-name hints into the system prompt for Pipeline (STRUCTURED) mode.

    The pipeline can't call tools natively, so we tell the model which operations
    are available and ask it to output structured JSON describing mutations.
    """
    system_text = system if isinstance(system, str) else "\n".join(system)
    if not tools:
        return system_text
    tool_names = ", ".join(t.get("name", "") for t in tools)
    hint = (
        f"\n\nAvailable operations: {tool_names}. "
        "If you need to make changes, describe them as a JSON list under the key "
        '"mutations": [{"op": "<operation>", ...}] at the end of your response.'
    )
    return system_text + hint


def _is_retriable(exc: Exception) -> bool:
    """Return True for errors that warrant trying the next backend in the chain."""
    try:
        import anthropic
        if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
            return True
    except ImportError:
        pass
    return False


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall]
    stop_reason: str        # "end_turn" | "tool_use" | "max_tokens"
    input_tokens: int
    output_tokens: int


class LLMBackend(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        system: str | list[str],
        model: str,
        tools: list[dict] | None = None,
        thinking: bool = False,
        thinking_budget: int = 8000,
        max_tokens: int = 8096,
    ) -> LLMResponse: ...

    @abstractmethod
    def is_available(self) -> bool: ...


# ---------------------------------------------------------------------------
# PipelineBackend — always available, wraps claude -p subprocess
# ---------------------------------------------------------------------------

class PipelineBackend(LLMBackend):
    """Invokes claude -p as a subprocess. Always available as fallback."""

    def is_available(self) -> bool:
        return True

    async def complete(
        self,
        messages: list[dict],
        system: str | list[str],
        model: str,
        tools: list[dict] | None = None,
        thinking: bool = False,
        thinking_budget: int = 8000,
        max_tokens: int = 8096,
    ) -> LLMResponse:
        # Collapse messages into a single prompt string for -p mode
        prompt_parts = []
        if isinstance(system, list):
            prompt_parts.append("\n".join(system))
        else:
            prompt_parts.append(system)
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt_parts.append(f"\n[{role}]\n{content}")
        prompt = "\n".join(prompt_parts)

        cmd = ["claude", "-p", "--strict-mcp-config", "--model", model, prompt]
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, check=True, timeout=180
        )
        return LLMResponse(
            content=result.stdout.strip(),
            tool_calls=[],
            stop_reason="end_turn",
            input_tokens=0,
            output_tokens=0,
        )


# ---------------------------------------------------------------------------
# AnthropicBackend — native tool_use via SDK, OAuth or API key
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 15.0  # seconds — subscription rate limits need real waits


class AnthropicBackend(LLMBackend):
    """Uses the Anthropic Python SDK. Prefers OAuth subscription billing,
    falls back to ANTHROPIC_API_KEY env var."""

    def __init__(self, credentials_path: str = _DEFAULT_CREDENTIALS_PATH):
        self._credentials_path = credentials_path

    async def _call_with_retry(self, client, kwargs: dict):
        """Call client.messages.create with exponential backoff on 429s.
        Respects retry-after header from the API if present."""
        import anthropic
        for attempt in range(_MAX_RETRIES):
            try:
                return await client.messages.create(**kwargs)
            except anthropic.RateLimitError as e:
                if attempt == _MAX_RETRIES - 1:
                    raise
                # Check for retry-after header
                retry_after = None
                if hasattr(e, 'response') and e.response is not None:
                    retry_after = e.response.headers.get("retry-after")
                    logger.warning("Rate limit response headers: %s",
                                   dict(e.response.headers))
                if retry_after:
                    delay = float(retry_after)
                else:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning("Rate limited, retrying in %.1fs (attempt %d/%d)",
                               delay, attempt + 1, _MAX_RETRIES)
                await asyncio.sleep(delay)

    def _get_oauth_token(self) -> str | None:
        """Get a valid OAuth token, refreshing if needed."""
        from bot.oauth import get_valid_token
        return get_valid_token(self._credentials_path)

    def is_available(self) -> bool:
        if self._get_oauth_token():
            return True
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    async def complete(
        self,
        messages: list[dict],
        system: str | list[str],
        model: str,
        tools: list[dict] | None = None,
        thinking: bool = False,
        thinking_budget: int = 8000,
        max_tokens: int = 8096,
    ) -> LLMResponse:
        import anthropic
        from bot.llm_adapters import to_anthropic_schema

        oauth_token = self._get_oauth_token()
        api_key = os.environ.get("ANTHROPIC_API_KEY")

        betas = []
        if oauth_token:
            betas.append("oauth-2025-04-20")
        if thinking:
            betas.append("interleaved-thinking-2025-05-14")

        default_headers = {}
        if betas:
            default_headers["anthropic-beta"] = ",".join(betas)

        if oauth_token:
            client = anthropic.AsyncAnthropic(
                auth_token=oauth_token,
                default_headers=default_headers,
                max_retries=0,  # we handle retries ourselves
            )
        else:
            client = anthropic.AsyncAnthropic(
                api_key=api_key,
                default_headers=default_headers if default_headers else None,
                max_retries=0,
            )

        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            system=system if isinstance(system, str) else "\n".join(system),
            messages=messages,
        )
        if tools:
            kwargs["tools"] = [to_anthropic_schema(t) for t in tools]
        if thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

        logger.info("anthropic request: model=%s, messages=%d, tools=%d, thinking=%s, max_tokens=%d",
                    kwargs.get("model"), len(kwargs.get("messages", [])),
                    len(kwargs.get("tools", []) or []), bool(kwargs.get("thinking")),
                    kwargs.get("max_tokens", 0))

        response = await self._call_with_retry(client, kwargs)

        content_text = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                ))

        logger.info("anthropic response: in=%d out=%d stop=%s tool_calls=%d (%s)",
                    response.usage.input_tokens, response.usage.output_tokens,
                    response.stop_reason, len(tool_calls),
                    ", ".join(tc.name for tc in tool_calls) or "none")

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


# ---------------------------------------------------------------------------
# OpenAIBackend — OpenAI-compatible API
# ---------------------------------------------------------------------------

class OpenAIBackend(LLMBackend):
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def complete(
        self,
        messages: list[dict],
        system: str | list[str],
        model: str,
        tools: list[dict] | None = None,
        thinking: bool = False,
        thinking_budget: int = 8000,
        max_tokens: int = 8096,
    ) -> LLMResponse:
        import openai
        from bot.llm_adapters import to_openai_schema

        system_text = system if isinstance(system, str) else "\n".join(system)
        full_messages = [{"role": "system", "content": system_text}] + messages

        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            messages=full_messages,
        )
        if self._base_url:
            client = openai.AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        else:
            client = openai.AsyncOpenAI(api_key=self._api_key)

        if tools:
            kwargs["tools"] = [to_openai_schema(t) for t in tools]

        response = await client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=json.loads(tc.function.arguments),
                ))

        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            stop_reason=response.choices[0].finish_reason or "end_turn",
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )


# ---------------------------------------------------------------------------
# OpenRouterBackend — OpenAI-compatible, different base URL + API key env
# ---------------------------------------------------------------------------

class OpenRouterBackend(OpenAIBackend):
    def __init__(self, api_key: str | None = None):
        super().__init__(
            api_key=api_key or os.environ.get("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
        )

    def is_available(self) -> bool:
        return bool(self._api_key)


# ---------------------------------------------------------------------------
# AWSBedrockBackend — via boto3 bedrock-runtime, ambient AWS credentials
# ---------------------------------------------------------------------------

class AWSBedrockBackend(LLMBackend):
    def __init__(self, region: str = "us-east-1"):
        self._region = region

    def is_available(self) -> bool:
        try:
            import boto3
            session = boto3.Session()
            creds = session.get_credentials()
            if creds is None:
                return False
            frozen = creds.get_frozen_credentials()
            return bool(frozen.access_key)
        except Exception:
            return False

    async def complete(
        self,
        messages: list[dict],
        system: str | list[str],
        model: str,
        tools: list[dict] | None = None,
        thinking: bool = False,
        thinking_budget: int = 8000,
        max_tokens: int = 8096,
    ) -> LLMResponse:
        import boto3
        from bot.llm_adapters import to_bedrock_schema

        client = boto3.client("bedrock-runtime", region_name=self._region)
        system_text = system if isinstance(system, str) else "\n".join(system)

        kwargs: dict = dict(
            modelId=model,
            system=[{"text": system_text}],
            messages=messages,
            inferenceConfig={"maxTokens": max_tokens},
        )
        if tools:
            kwargs["toolConfig"] = {"tools": [to_bedrock_schema(t) for t in tools]}

        response = await asyncio.to_thread(client.converse, **kwargs)
        output = response["output"]["message"]

        content_text = ""
        tool_calls = []
        for block in output.get("content", []):
            if "text" in block:
                content_text += block["text"]
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(ToolCall(id=tu["toolUseId"], name=tu["name"], input=tu["input"]))

        usage = response.get("usage", {})
        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            stop_reason=response["stopReason"],
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
        )


# ---------------------------------------------------------------------------
# AgentSDKBackend — Sonnet via claude binary (bypasses subscription gating)
# ---------------------------------------------------------------------------

def _format_messages_as_prompt(messages: list[dict], system: str | list[str]) -> str:
    """Flatten system + messages into a single string prompt for the Agent SDK.

    The Agent SDK takes a single prompt string (or system_prompt separately).
    We join conversation history so the model has full context.
    """
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # Handle list content (tool results, etc.) — extract text blocks
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        text_parts.append(f"[tool result: {block.get('content', '')}]")
                else:
                    text_parts.append(str(block))
            content = "\n".join(text_parts)
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)


class AgentSDKBackend(LLMBackend):
    """Uses claude-agent-sdk to spawn the claude binary for Sonnet access.

    The claude binary passes server-side gating that raw SDK calls do not.
    Optionally connects to the tether MCP server so Claude can call
    tether tools (get_plan, upsert_task, etc.) natively.

    Does NOT return tool_calls — tool use is handled internally by claude.
    The LLMResponse always has tool_calls=[] and stop_reason="end_turn".
    """

    def __init__(self, mcp_server_url: str | None = None):
        self._mcp_server_url = mcp_server_url

    def is_available(self) -> bool:
        try:
            import claude_agent_sdk  # noqa: F401
            result = subprocess.run(
                ["claude", "--version"], capture_output=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            return False

    async def complete(
        self,
        messages: list[dict],
        system: str | list[str],
        model: str,
        tools: list[dict] | None = None,
        thinking: bool = False,
        thinking_budget: int = 8000,
        max_tokens: int = 8096,
    ) -> LLMResponse:
        from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage
        from claude_agent_sdk.types import McpSSEServerConfig, ThinkingConfigEnabled

        system_text = system if isinstance(system, str) else "\n".join(system)
        prompt = _format_messages_as_prompt(messages, system)

        mcp_servers: dict = {}
        if self._mcp_server_url:
            mcp_servers["tether"] = McpSSEServerConfig(url=self._mcp_server_url)

        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system_text,
            max_turns=12,
            mcp_servers=mcp_servers,
            permission_mode="bypassPermissions",
            # Disable all Claude Code native tools — only tether MCP tools are allowed
            disallowed_tools=_CLAUDE_CODE_NATIVE_TOOLS,
        )
        if thinking:
            options.thinking = ThinkingConfigEnabled(budget_tokens=thinking_budget)

        logger.info("agent-sdk request: model=%s, mcp=%s, thinking=%s",
                    model, bool(mcp_servers), thinking)

        content_text = ""
        result_msg: ResultMessage | None = None

        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        content_text += block.text
            elif isinstance(msg, ResultMessage):
                result_msg = msg

        usage = result_msg.usage or {} if result_msg else {}
        stop_reason = (result_msg.stop_reason or "end_turn") if result_msg else "end_turn"

        logger.info("agent-sdk response: turns=%s stop=%s cost=$%.4f",
                    result_msg.num_turns if result_msg else "?",
                    stop_reason,
                    result_msg.total_cost_usd or 0 if result_msg else 0)

        return LLMResponse(
            content=content_text.strip(),
            tool_calls=[],
            stop_reason=stop_reason,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )


# ---------------------------------------------------------------------------
# LLMRouter — role-based routing with per-vendor fallback chains
# ---------------------------------------------------------------------------

class LLMRouter:
    """Routes LLM calls by role → (vendor, model) → fallback chain.

    Fallback chains:
      anthropic: AnthropicBackend (NATIVE) → AgentSDKBackend (MCP) → PipelineBackend (STRUCTURED)
      openai / openrouter / bedrock: direct SDK only — failures propagate

    Usage:
      response = await router.complete(role="classifier", messages=[...], system="...")
      response = await router.complete(role="main_agent", messages=[...], system="...", tools=[...])

    Backward-compat attributes:
      router.active_backend — AgentSDKBackend or PipelineBackend (full reasoning)
      router.fast_backend   — AnthropicBackend or PipelineBackend (cheap calls)
    """

    def __init__(
        self,
        credentials_path: str = _DEFAULT_CREDENTIALS_PATH,
        mcp_server_url: str | None = None,
        roles_config: dict | None = None,
    ):
        # Pre-build all vendor backends (cheap — no network calls)
        self._anthropic = AnthropicBackend(credentials_path=credentials_path)
        self._agent_sdk = AgentSDKBackend(mcp_server_url=mcp_server_url)
        self._openai = OpenAIBackend()
        self._openrouter = OpenRouterBackend()
        self._bedrock = AWSBedrockBackend()
        self._pipeline = PipelineBackend()

        # Merge caller-supplied roles over defaults
        self._roles: dict[str, dict[str, str]] = {**_DEFAULT_ROLES, **(roles_config or {})}

        # Backward-compat attributes
        self.active_backend: LLMBackend = (
            self._agent_sdk if self._agent_sdk.is_available() else self._pipeline
        )
        self.fast_backend: LLMBackend = (
            self._anthropic if self._anthropic.is_available() else self._pipeline
        )

        logger.info("LLMRouter ready: active=%s fast=%s roles=%d",
                    type(self.active_backend).__name__,
                    type(self.fast_backend).__name__,
                    len(self._roles))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_role(self, role: str) -> tuple[str, str]:
        """Return (vendor, model) for a role. Falls back to main_agent defaults."""
        cfg = self._roles.get(role) or self._roles.get("main_agent") or {}
        vendor = cfg.get("vendor", "anthropic")
        model = cfg.get("model", "claude-sonnet-4-6")
        return vendor, model

    def _build_chain(self, vendor: str) -> list[tuple[LLMBackend, ToolMode]]:
        """Build the ordered fallback chain for a given vendor."""
        if vendor == "anthropic":
            chain: list[tuple[LLMBackend, ToolMode]] = []
            if self._anthropic.is_available():
                chain.append((self._anthropic, ToolMode.NATIVE))
            if self._agent_sdk.is_available():
                chain.append((self._agent_sdk, ToolMode.MCP))
            chain.append((self._pipeline, ToolMode.STRUCTURED))
            return chain
        elif vendor == "openai":
            return [(self._openai, ToolMode.NATIVE)] if self._openai.is_available() else []
        elif vendor == "openrouter":
            return [(self._openrouter, ToolMode.NATIVE)] if self._openrouter.is_available() else []
        elif vendor == "bedrock":
            return [(self._bedrock, ToolMode.NATIVE)] if self._bedrock.is_available() else []
        # Unknown vendor — fall through to pipeline
        return [(self._pipeline, ToolMode.STRUCTURED)]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def complete(
        self,
        role: str = "main_agent",
        messages: list[dict] | None = None,
        system: str | list[str] = "",
        tools: list[dict] | None = None,
        thinking: bool | None = None,
        thinking_budget: int = 8000,
        max_tokens: int = 8096,
        # Backward-compat: accept but ignore bare model/kwargs from old callers
        **_ignored,
    ) -> LLMResponse:
        """Complete a request for a named role, trying each backend in the fallback chain."""
        vendor, model = self._resolve_role(role)
        chain = self._build_chain(vendor)
        if not chain:
            raise RuntimeError(f"No backend available for vendor={vendor!r}, role={role!r}")

        # Auto-enable thinking for Sonnet-tier models unless caller overrides
        if thinking is None:
            thinking = "sonnet" in model or "opus" in model

        last_exc: Exception | None = None
        for backend, tool_mode in chain:
            effective_tools = tools
            effective_system = system

            if tool_mode == ToolMode.MCP:
                effective_tools = None  # Agent SDK calls tools via MCP internally
            elif tool_mode == ToolMode.STRUCTURED:
                effective_tools = None
                effective_system = _add_structured_output_hint(system, tools)
                thinking = False  # Pipeline doesn't support extended thinking

            logger.info("router.complete: role=%s vendor=%s model=%s backend=%s tool_mode=%s",
                        role, vendor, model, type(backend).__name__, tool_mode.name)
            try:
                return await backend.complete(
                    messages=messages or [],
                    system=effective_system,
                    model=model,
                    tools=effective_tools,
                    thinking=thinking,
                    thinking_budget=thinking_budget,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                if _is_retriable(exc):
                    logger.warning("router: %s failed for role=%s (%s) — trying next backend",
                                   type(backend).__name__, role, exc)
                    last_exc = exc
                    continue
                raise  # Non-retriable errors propagate immediately

        # All backends in chain exhausted
        if last_exc:
            raise last_exc
        raise RuntimeError(f"All backends exhausted for vendor={vendor!r}, role={role!r}")

    async def complete_fast(self, role: str = "classifier", **kwargs) -> LLMResponse:
        """Convenience: complete with fast backend for simple/cheap calls."""
        return await self.complete(role=role, **kwargs)
