from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from bookshelf import agent, llm, tracing
from bookshelf.config import Settings, TracingSettings


class RecordingTracer:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flushed = False

    @contextmanager
    def observe(
        self,
        name: str,
        *,
        as_type: str = "span",
        input: Any = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[tracing.Observation]:
        event: dict[str, Any] = {"name": name, "as_type": as_type, "input": input, "model": model}
        self.events.append(event)

        class Obs:
            def update(self, **fields: Any) -> None:
                event.update(fields)

        yield Obs()

    def flush(self) -> None:
        self.flushed = True


class ScriptedClient:
    provider = "fake"
    model = "fake-1"

    def __init__(self, responses: list[llm.ChatResponse]) -> None:
        self._responses = list(responses)

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> llm.ChatResponse:
        return self._responses.pop(0)


def test_tracing_is_off_without_keys() -> None:
    assert TracingSettings(langfuse_public_key=None, langfuse_secret_key=None).enabled is False
    assert isinstance(tracing.get_tracer(TracingSettings()), tracing.NoopTracer)


def test_tracing_needs_both_keys_and_can_be_forced_off() -> None:
    keys = {"langfuse_public_key": "pk", "langfuse_secret_key": "sk"}

    on = {**keys, "langfuse_tracing_enabled": True}  # the autouse fixture forces the env off

    assert TracingSettings(**on).enabled is True
    only_public = TracingSettings(
        langfuse_public_key="pk", langfuse_secret_key=None, langfuse_tracing_enabled=True
    )
    assert only_public.enabled is False
    assert TracingSettings(**keys, langfuse_tracing_enabled=False).enabled is False


def test_agent_records_root_generations_and_tools(conn: sqlite3.Connection) -> None:
    tracer = RecordingTracer()
    client = ScriptedClient(
        [
            llm.ChatResponse(tool_calls=(llm.ToolCall("1", "library_stats", {}),)),
            llm.ChatResponse(content="Try Piranesi."),
        ]
    )

    result = agent.recommend(
        conn, query=" what next? ", settings=Settings(), client=client, tracer=tracer
    )

    assert result.answer == "Try Piranesi."
    assert [(e["name"], e["as_type"]) for e in tracer.events] == [
        ("recommend", "agent"),
        ("chat", "generation"),
        ("tool:library_stats", "tool"),
        ("chat", "generation"),
    ]
    root, first_chat, tool, last_chat = tracer.events
    assert root["input"] == "what next?"
    assert root["output"] == "Try Piranesi."
    assert first_chat["model"] == "fake-1"
    assert first_chat["output"]["tool_calls"] == [{"name": "library_stats", "arguments": {}}]
    assert '"total_books"' in tool["output"] or tool["output"].startswith("{")
    assert last_chat["output"]["content"] == "Try Piranesi."


def test_agent_works_without_a_tracer(conn: sqlite3.Connection) -> None:
    client = ScriptedClient([llm.ChatResponse(content="Hi.")])

    result = agent.recommend(conn, query="hello", settings=Settings(), client=client)

    assert result.answer == "Hi."


class FakeLangfuseClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.started: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.exits: list[Any] = []
        self.flushed = False

    @contextmanager
    def start_as_current_observation(self, **fields: Any) -> Iterator[Any]:
        if self.fail:
            raise RuntimeError("langfuse is down")
        self.started.append(fields)
        client = self

        class Span:
            def update(self, **update: Any) -> None:
                client.updates.append(update)

        yield Span()

    def flush(self) -> None:
        self.flushed = True


def test_langfuse_tracer_forwards_fields_and_flushes() -> None:
    client = FakeLangfuseClient()
    tracer = tracing.LangfuseTracer(client)

    with tracer.observe("chat", as_type="generation", input=["m"], model="qwen") as span:
        span.update(output="done")
    tracer.flush()

    assert client.started == [
        {"name": "chat", "as_type": "generation", "input": ["m"], "model": "qwen"}
    ]
    assert client.updates == [{"output": "done"}]
    assert client.flushed is True


def test_langfuse_failures_never_break_the_caller() -> None:
    tracer = tracing.LangfuseTracer(FakeLangfuseClient(fail=True))

    with tracer.observe("recommend") as span:
        span.update(output="still works")


def test_exceptions_inside_an_observation_propagate() -> None:
    tracer = tracing.LangfuseTracer(FakeLangfuseClient())

    with pytest.raises(ValueError, match="boom"), tracer.observe("recommend"):
        raise ValueError("boom")
