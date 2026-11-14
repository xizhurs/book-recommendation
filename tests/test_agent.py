from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from bookshelf import agent, llm
from bookshelf.config import LLMSettings, Settings


class FakeClient:
    provider = "fake"
    model = "fake-1"

    def __init__(self, responses: list[llm.ChatResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> llm.ChatResponse:
        self.calls.append((list(messages), tools))
        return self.responses.pop(0)


@pytest.fixture
def settings() -> Settings:
    return Settings(rerank_enabled=False, llm=LLMSettings(_env_file=None, llm_max_steps=4))


def test_answers_without_tools(conn: sqlite3.Connection, settings: Settings) -> None:
    client = FakeClient([llm.ChatResponse(content="Try Piranesi.")])

    result = agent.recommend(conn, query="something short", settings=settings, client=client)

    assert result.answer == "Try Piranesi."
    assert result.provider == "fake"
    assert result.model == "fake-1"
    assert result.steps == []
    assert len(client.calls) == 1
    messages, tools = client.calls[0]
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "something short"}
    assert tools is not None
    assert [spec["function"]["name"] for spec in tools] == [
        "search_library",
        "library_stats",
        "discover_books",
        "get_book",
    ]


def test_executes_tool_calls_then_answers(conn: sqlite3.Connection, settings: Settings) -> None:
    client = FakeClient(
        [
            llm.ChatResponse(
                content=None,
                tool_calls=(
                    llm.ToolCall(id="call_1", name="search_library", arguments={"query": "dune"}),
                ),
            ),
            llm.ChatResponse(content="You already own Dune."),
        ]
    )

    result = agent.recommend(conn, query="do I own Dune?", settings=settings, client=client)

    assert result.answer == "You already own Dune."
    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.name == "search_library"
    assert step.arguments == {"query": "dune"}
    assert json.loads(step.result)["total"] == 0

    second_messages, _ = client.calls[1]
    assistant = second_messages[2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["function"]["name"] == "search_library"
    tool_message = second_messages[3]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["content"] == step.result


def test_tool_errors_are_fed_back_to_the_model(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    client = FakeClient(
        [
            llm.ChatResponse(
                tool_calls=(llm.ToolCall(id="call_1", name="get_book", arguments={"book_id": 99}),)
            ),
            llm.ChatResponse(content="That id does not exist."),
        ]
    )

    result = agent.recommend(conn, query="book 99?", settings=settings, client=client)

    assert "no book with id 99" in result.steps[0].result
    assert result.answer == "That id does not exist."


def test_exhausted_budget_returns_a_fallback(conn: sqlite3.Connection, settings: Settings) -> None:
    tool_only = llm.ChatResponse(
        tool_calls=(llm.ToolCall(id="call_1", name="library_stats", arguments={}),)
    )
    client = FakeClient([tool_only, llm.ChatResponse(content=None)])

    result = agent.recommend(conn, query="stats?", settings=settings, client=client, max_steps=1)

    assert result.answer == agent.FALLBACK_ANSWER
    assert len(result.steps) == 1
    assert client.calls[1][1] is None


def test_max_steps_is_clamped_to_one_at_the_bottom(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    tool_only = llm.ChatResponse(
        tool_calls=(llm.ToolCall(id="call_1", name="library_stats", arguments={}),)
    )
    client = FakeClient([tool_only, llm.ChatResponse(content="Done.")])

    result = agent.recommend(conn, query="stats?", settings=settings, client=client, max_steps=0)

    assert result.answer == "Done."
    assert len(client.calls) == 2


def test_settings_supply_the_default_budget(
    conn: sqlite3.Connection,
) -> None:
    settings = Settings(
        rerank_enabled=False,
        llm=LLMSettings(_env_file=None, llm_max_steps=2),
    )
    tool_only = llm.ChatResponse(
        tool_calls=(llm.ToolCall(id="call_1", name="library_stats", arguments={}),)
    )
    client = FakeClient([tool_only, tool_only, llm.ChatResponse(content="Done.")])

    result = agent.recommend(conn, query="stats?", settings=settings, client=client)

    assert result.answer == "Done."
    assert len(client.calls) == 3
    assert len(result.steps) == 2
