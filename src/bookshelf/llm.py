"""One chat client for both hosted OpenAI and local Ollama.

Ollama exposes an OpenAI-compatible ``/v1/chat/completions`` endpoint, so the only things that
change between providers are the base URL, model name, and API key. Switching is therefore a
single environment variable (``LLM_PROVIDER=openai|ollama``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import LLMSettings


class LLMError(RuntimeError):
    """The provider was unreachable, misconfigured, or returned an unusable response."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResponse:
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


class ChatClient(Protocol):
    provider: str
    model: str

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse: ...


class OpenAICompatibleClient:
    """Chat-completions client that works against OpenAI and Ollama."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        api_key: str | None,
        timeout: float = 90.0,
        temperature: float = 0.2,
        extra_body: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        self.extra_body = dict(extra_body or {})
        self.transport = transport

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            **self.extra_body,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.Client(
                timeout=self.timeout,
                headers=headers,
                transport=self.transport,
                follow_redirects=True,
            ) as client:
                response = client.post(f"{self.base_url}/chat/completions", json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _error_detail(exc.response)
            suffix = f": {detail}" if detail else ""
            raise LLMError(f"{self.provider} request failed: {exc}{suffix}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.provider} request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMError(f"{self.provider} returned invalid JSON") from exc

        return _parse_response(data, provider=self.provider)


def _error_detail(response: httpx.Response) -> str:
    """The provider's own error message (OpenAI and Ollama both use ``{"error": ...}``).

    Error bodies echo the problem (bad parameter, unknown model), not the request, so this
    never includes the prompt or library data.
    """
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return ""
    if isinstance(error, dict):
        error = error.get("message")
    return str(error)[:500] if error else ""


def _parse_response(data: object, *, provider: str) -> ChatResponse:
    if not isinstance(data, dict):
        raise LLMError(f"{provider} returned an unexpected payload")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError(f"{provider} returned no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMError(f"{provider} returned an unexpected choice")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMError(f"{provider} returned no message")

    content = message.get("content")
    raw_calls = message.get("tool_calls")
    calls: list[ToolCall] = []
    if isinstance(raw_calls, list):
        for index, raw in enumerate(raw_calls):
            if not isinstance(raw, dict):
                continue
            function = raw.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            call_id = raw.get("id")
            calls.append(
                ToolCall(
                    id=call_id if isinstance(call_id, str) and call_id else f"call_{index}",
                    name=name,
                    arguments=_parse_arguments(function.get("arguments")),
                )
            )

    return ChatResponse(
        content=content if isinstance(content, str) and content.strip() else None,
        tool_calls=tuple(calls),
    )


def _parse_arguments(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_client(
    settings: LLMSettings, *, transport: httpx.BaseTransport | None = None
) -> ChatClient:
    """Build the configured provider. Both providers share one implementation."""
    if settings.llm_provider == "openai":
        api_key = (
            settings.openai_api_key.get_secret_value().strip()
            if settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise LLMError(
                "OPENAI_API_KEY is not set; set LLM_PROVIDER=ollama or provide a key in .env"
            )
        return OpenAICompatibleClient(
            provider="openai",
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            api_key=api_key,
            timeout=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            extra_body=(
                {"reasoning_effort": effort}
                if (effort := settings.openai_reasoning_effort.strip())
                else None
            ),
            transport=transport,
        )
    return OpenAICompatibleClient(
        provider="ollama",
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        api_key="ollama",
        timeout=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
        transport=transport,
    )
