from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from bookshelf import agent, llm, repository, tracing
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
        session_id: str | None = None,
    ) -> Iterator[tracing.Observation]:
        event: dict[str, Any] = {
            "name": name,
            "as_type": as_type,
            "input": input,
            "model": model,
            "session_id": session_id,
        }
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


def test_langfuse_tracer_propagates_session_id_around_the_observation() -> None:
    order: list[str] = []

    @contextmanager
    def propagate(**attrs: Any) -> Iterator[None]:
        order.append(f"enter:{attrs['session_id']}")
        yield
        order.append("exit")

    client = FakeLangfuseClient()
    tracer = tracing.LangfuseTracer(client, propagate=propagate)

    with tracer.observe("recommend", session_id="chat-1"):
        order.append("body")

    assert order == ["enter:chat-1", "body", "exit"]
    assert len(client.started) == 1


def test_langfuse_tracer_skips_propagation_without_session_id() -> None:
    def propagate(**attrs: Any) -> Any:
        raise AssertionError("should not be called")

    tracer = tracing.LangfuseTracer(FakeLangfuseClient(), propagate=propagate)

    with tracer.observe("recommend"):
        pass


def test_session_propagation_failure_never_breaks_the_caller() -> None:
    def propagate(**attrs: Any) -> Any:
        raise RuntimeError("no otel")

    tracer = tracing.LangfuseTracer(FakeLangfuseClient(), propagate=propagate)

    with tracer.observe("recommend", session_id="s") as span:
        span.update(output="fine")


def test_agent_passes_session_id_to_the_root_observation(conn: sqlite3.Connection) -> None:
    tracer = RecordingTracer()
    client = ScriptedClient([llm.ChatResponse(content="Read Dune.")])

    agent.recommend(
        conn, query="next?", settings=Settings(), client=client, tracer=tracer, session_id="s-1"
    )

    assert tracer.events[0]["session_id"] == "s-1"


class RecordingClient(ScriptedClient):
    def __init__(self, responses: list[llm.ChatResponse]) -> None:
        super().__init__(responses)
        self.seen: list[list[dict[str, Any]]] = []

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> llm.ChatResponse:
        self.seen.append([dict(m) for m in messages])
        return super().chat(messages, tools)


def test_session_memory_replays_earlier_turns(conn: sqlite3.Connection) -> None:
    client = RecordingClient(
        [llm.ChatResponse(content="Try Emma."), llm.ChatResponse(content="Try Dune.")]
    )

    agent.recommend(conn, query="after Austen?", settings=Settings(), client=client, session_id="s")
    agent.recommend(
        conn, query="something newer?", settings=Settings(), client=client, session_id="s"
    )

    first, second = client.seen
    assert [m["role"] for m in first] == ["system", "user"]
    assert [(m["role"], m["content"]) for m in second[1:]] == [
        ("user", "after Austen?"),
        ("assistant", "Try Emma."),
        ("user", "something newer?"),
    ]


def test_memory_is_isolated_per_session_and_off_without_one(conn: sqlite3.Connection) -> None:
    client = RecordingClient([llm.ChatResponse(content=f"a{i}") for i in range(3)])

    agent.recommend(conn, query="q1", settings=Settings(), client=client, session_id="a")
    agent.recommend(conn, query="q2", settings=Settings(), client=client, session_id="b")
    agent.recommend(conn, query="q3", settings=Settings(), client=client)

    assert all(len(messages) == 2 for messages in client.seen)
    assert conn.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0] == 2


def test_memory_is_capped_and_skips_fallback_answers(conn: sqlite3.Connection) -> None:
    for i in range(agent.MEMORY_TURNS + 2):
        repository.append_conversation_turn(conn, "s", f"q{i}", f"a{i}")
    client = RecordingClient([llm.ChatResponse(content="")] * 2)

    agent.recommend(conn, query="now", settings=Settings(), client=client, session_id="s")

    seen = client.seen[0]
    assert len(seen) == 1 + 2 * agent.MEMORY_TURNS + 1
    assert seen[1]["content"] == "q2"
    assert repository.get_conversation(conn, "s", limit=100)[-1] == ("q7", "a7")
