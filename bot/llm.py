"""LLM abstraction layer for Tether v3.

Provides a vendor-agnostic interface for LLM completions.
LLMRouter selects the best available backend at startup with
PipelineBackend (claude -p) always available as fallback.
"""
import asyncio
import os
import json
import time
import subprocess
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DEFAULT_CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")


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
_RETRY_BASE_DELAY = 2.0  # seconds, doubles each retry


class AnthropicBackend(LLMBackend):
    """Uses the Anthropic Python SDK. Prefers OAuth subscription billing,
    falls back to ANTHROPIC_API_KEY env var."""

    def __init__(self, credentials_path: str = _DEFAULT_CREDENTIALS_PATH):
        self._credentials_path = credentials_path

    async def _call_with_retry(self, client, kwargs: dict):
        """Call client.messages.create with exponential backoff on 429s."""
        import anthropic
        for attempt in range(_MAX_RETRIES):
            try:
                return await client.messages.create(**kwargs)
            except anthropic.RateLimitError:
                if attempt == _MAX_RETRIES - 1:
                    raise
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
            )
        else:
            client = anthropic.AsyncAnthropic(
                api_key=api_key,
                default_headers=default_headers if default_headers else None,
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
# LLMRouter — selects best available backend
# ---------------------------------------------------------------------------

class LLMRouter:
    """Picks the best available LLM backend at construction time.
    Priority: AnthropicBackend → configured vendor → PipelineBackend.
    """

    def __init__(self, credentials_path: str = _DEFAULT_CREDENTIALS_PATH):
        self.active_backend = self._select(credentials_path)

    def _select(self, credentials_path: str) -> LLMBackend:
        candidates: list[LLMBackend] = [
            AnthropicBackend(credentials_path=credentials_path),
            OpenAIBackend(),
            OpenRouterBackend(),
            AWSBedrockBackend(),
            PipelineBackend(),
        ]
        for backend in candidates:
            if backend.is_available():
                logger.info("LLMRouter selected backend: %s", type(backend).__name__)
                return backend
        return PipelineBackend()  # unreachable — Pipeline is always available

    async def complete(self, **kwargs) -> LLMResponse:
        return await self.active_backend.complete(**kwargs)
