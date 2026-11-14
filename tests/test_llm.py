from __future__ import annotations

import json

import httpx
import pytest

from bookshelf import llm
from bookshelf.config import LLMSettings


def make_client(handler: httpx.BaseTransport) -> llm.OpenAICompatibleClient:
    return llm.OpenAICompatibleClient(
        provider="ollama",
        model="test-model",
        base_url="http://llm.local/v1",
        api_key="test-key",
        transport=handler,
    )


def test_build_client_defaults_to_local_ollama() -> None:
    client = llm.build_client(LLMSettings(_env_file=None))

    assert client.provider == "ollama"
    assert client.model == "qwen3.5:4b"
    assert isinstance(client, llm.OpenAICompatibleClient)
    assert client.base_url == "http://127.0.0.1:11434/v1"


def test_build_client_selects_openai_and_uses_the_key() -> None:
    settings = LLMSettings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key="sk-test",
        openai_model="gpt-test",
    )

    client = llm.build_client(settings)

    assert client.provider == "openai"
    assert client.model == "gpt-test"
    assert isinstance(client, llm.OpenAICompatibleClient)
    assert client.api_key == "sk-test"


def test_build_client_requires_an_openai_key() -> None:
    settings = LLMSettings(_env_file=None, llm_provider="openai", openai_api_key=None)

    with pytest.raises(llm.LLMError, match="OPENAI_API_KEY"):
        llm.build_client(settings)


def test_chat_sends_openai_compatible_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Hello."}}]},
        )

    response = make_client(httpx.MockTransport(handler)).chat(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "x"}}],
    )

    assert captured["url"] == "http://llm.local/v1/chat/completions"
    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "test-model"
    assert body["tool_choice"] == "auto"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert response.content == "Hello."
    assert response.tool_calls == ()


def test_chat_parses_tool_calls_and_json_arguments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_library",
                                        "arguments": '{"query": "dune", "limit": 2}',
                                    },
                                },
                                {
                                    "function": {
                                        "name": "library_stats",
                                        "arguments": {},
                                    }
                                },
                            ],
                        }
                    }
                ]
            },
        )

    response = make_client(httpx.MockTransport(handler)).chat([])

    assert response.content is None
    assert response.tool_calls[0] == llm.ToolCall(
        id="call_1", name="search_library", arguments={"query": "dune", "limit": 2}
    )
    assert response.tool_calls[1].id == "call_1"


def test_chat_falls_back_to_empty_arguments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {"name": "get_book", "arguments": "not json"},
                                }
                            ]
                        }
                    }
                ]
            },
        )

    response = make_client(httpx.MockTransport(handler)).chat([])

    assert response.tool_calls == (llm.ToolCall(id="call_1", name="get_book", arguments={}),)


def test_chat_reports_http_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(llm.LLMError, match="ollama request failed"):
        make_client(httpx.MockTransport(handler)).chat([])


def test_chat_reports_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with pytest.raises(llm.LLMError, match="invalid JSON"):
        make_client(httpx.MockTransport(handler)).chat([])


def test_chat_reports_missing_choices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(llm.LLMError, match="no choices"):
        make_client(httpx.MockTransport(handler)).chat([])
