"""LLM abstraction layer for Tether.

Provides a vendor-agnostic interface for LLM completions.
Base types (LLMBackend, LLMResponse, ToolCall) and backend implementations
for Anthropic, OpenAI, OpenRouter, Bedrock, and Pipeline (claude agent SDK).

Advanced features (LLMRouter with fallback chains, AgentSDKBackend,
multi-turn sessions) are available via tether-premium.
"""
import asyncio
import contextvars
import os
import json
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Per-request env extras — set by handle_message() when a vault is provided so
# that all LLM calls in the same request inherit per-user credentials (typically
# {"CLAUDE_CODE_OAUTH_TOKEN": "<oauth-token>"}). Never set this at module
# level; always use .set()/.reset().
_llm_env_extras: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "_llm_env_extras", default=None
)

logger = logging.getLogger(__name__)

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
    """Invokes the Claude agent SDK. Always available as fallback."""

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
        from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

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

        env: dict[str, str] = {}
        extras = _llm_env_extras.get()
        if extras:
            env.update(extras)

        opts = ClaudeAgentOptions(
            model=model,
            permission_mode="bypassPermissions",
            env=env,
        )

        async def _collect() -> str:
            parts: list[str] = []
            async for msg in query(prompt=prompt, options=opts):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            parts.append(block.text)
            return "".join(parts).strip()

        output = await asyncio.wait_for(_collect(), timeout=180)
        return LLMResponse(
            content=output,
            tool_calls=[],
            stop_reason="end_turn",
            input_tokens=0,
            output_tokens=0,
        )


# ---------------------------------------------------------------------------
# AnthropicBackend — native tool_use via SDK, OAuth or API key
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 15.0


class AnthropicBackend(LLMBackend):
    """Uses the Anthropic Python SDK. Prefers OAuth subscription billing,
    falls back to ANTHROPIC_API_KEY env var."""

    async def _call_with_retry(self, client, kwargs: dict):
        """Call client.messages.create with exponential backoff on 429s."""
        import anthropic
        for attempt in range(_MAX_RETRIES):
            try:
                return await client.messages.create(**kwargs)
            except anthropic.RateLimitError as e:
                if attempt == _MAX_RETRIES - 1:
                    raise
                retry_after = None
                if hasattr(e, 'response') and e.response is not None:
                    retry_after = e.response.headers.get("retry-after")
                if retry_after:
                    delay = float(retry_after)
                else:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning("Rate limited, retrying in %.1fs (attempt %d/%d)",
                               delay, attempt + 1, _MAX_RETRIES)
                await asyncio.sleep(delay)

    def _get_oauth_token(self) -> str | None:
        extras = _llm_env_extras.get()
        if extras:
            return extras.get("CLAUDE_CODE_OAUTH_TOKEN")
        return None

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
                max_retries=0,
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

        try:
            response = await self._call_with_retry(client, kwargs)
        except anthropic.AuthenticationError as e:
            source = "OAuth" if oauth_token else "API key"
            logger.error("Anthropic auth failed (%s): %s", source, e)
            raise RuntimeError(
                "Anthropic credentials not configured — reconnect via Settings → Integrations → Anthropic."
            ) from e

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

        kwargs: dict = dict(model=model, max_tokens=max_tokens, messages=full_messages)
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
