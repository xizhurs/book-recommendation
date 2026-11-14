"""LLM-driven retrieval loop: the model picks tools, we execute them, it answers.

Provider selection is delegated to ``llm.build_client``; nothing here is OpenAI- or
Ollama-specific.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import llm, repository, tools, tracing
from .config import Settings
from .models import Recommendation, ToolCallRecord

SYSTEM_PROMPT = (
    "You are a personal bookshelf assistant running on the reader's machine. "
    "Ground every claim in tool results.\n"
    "- Use search_library to understand what the reader owns, likes, and has read.\n"
    "- Use discover_books to suggest titles they do not own; never invent titles or authors.\n"
    "- Use library_stats for overview questions and get_book to look up one id.\n"
    "- If a search returns nothing, retry once with a corrected spelling; results marked "
    "fuzzy are near matches for a misspelled query, so say which title you assumed.\n"
    "- Review text is private and unavailable; do not ask for it or claim to have read it.\n"
    "- Earlier questions and answers from this conversation may precede the new question; "
    "use them to resolve references such as 'another', 'more recent' or 'that author'.\n"
    "- discover_books is a plain keyword search with no notion of 'similar to'; topic or genre "
    "queries return noise (essays, biographies, unrelated classics). To recommend new books, "
    "name specific candidates from your own knowledge of similar books, then confirm each with "
    "discover_books using its exact title and author. Recommend only books that search "
    "confirmed exist and are not already owned; say so if none could be confirmed.\n"
    "- Do not repeat titles you already suggested earlier in this conversation unless asked.\n"
    "- Keep the final answer short: a few suggestions, each with one line of reasoning."
)

FINAL_ANSWER_PROMPT = (
    "You have no tool calls left. Answer now using only the tool results above; "
    "do not request more tools."
)

FALLBACK_ANSWER = (
    "I could not settle on an answer within the tool budget. "
    "Try a narrower request, or raise llm_max_steps."
)

MAX_STEP_RECORD_CHARS = 4000
MEMORY_TURNS = 6
MEMORY_ANSWER_CHARS = 1500


def recommend(
    conn: sqlite3.Connection,
    *,
    query: str,
    settings: Settings,
    client: llm.ChatClient | None = None,
    max_steps: int | None = None,
    tracer: tracing.Tracer | None = None,
    session_id: str | None = None,
) -> Recommendation:
    """Run the tool-calling loop until the model answers or the step budget runs out.

    When tracing is configured, the run is recorded as one ``recommend`` observation with a
    generation per model turn and a tool observation per tool call. ``session_id`` groups runs
    into one Langfuse session and, because it also keys conversation memory, the last
    ``MEMORY_TURNS`` question/answer pairs of that session are replayed to the model and this
    turn is saved. Without a session id every call is stateless.
    """
    chat = client if client is not None else llm.build_client(settings.llm)
    budget = _clamp(max_steps if max_steps is not None else settings.llm.llm_max_steps, 1, 8)
    tracer = tracer if tracer is not None else tracing.get_tracer(settings.tracing)
    session_id = session_id or None
    history = (
        repository.get_conversation(conn, session_id, limit=MEMORY_TURNS) if session_id else []
    )

    with tracer.observe(
        "recommend",
        as_type="agent",
        input=query.strip(),
        metadata={"provider": chat.provider, "model": chat.model, "max_steps": budget},
        session_id=session_id,
    ) as root:
        result = _run(conn, query, settings, chat, budget, tracer, history)
        root.update(
            output=result.answer,
            metadata={"tool_calls": len(result.steps), "memory_turns": len(history)},
        )
        if session_id and result.answer != FALLBACK_ANSWER:
            repository.append_conversation_turn(conn, session_id, query.strip(), result.answer)
        return result


def _run(
    conn: sqlite3.Connection,
    query: str,
    settings: Settings,
    chat: llm.ChatClient,
    budget: int,
    tracer: tracing.Tracer,
    history: list[tuple[str, str]],
) -> Recommendation:
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for question, answer in history:
        messages.append({"role": "user", "content": question})
        messages.append({"role": "assistant", "content": answer[:MEMORY_ANSWER_CHARS]})
    messages.append({"role": "user", "content": query.strip()})
    steps: list[ToolCallRecord] = []

    for _ in range(budget):
        response = _chat(chat, tracer, messages, tools.tool_specs())
        if not response.tool_calls:
            return _result(response.content, chat, steps)

        messages.append(_assistant_message(response))
        for call in response.tool_calls:
            with tracer.observe("tool:" + call.name, as_type="tool", input=call.arguments) as span:
                result = tools.call_tool(conn, settings, call.name, call.arguments)
                span.update(output=result[:MAX_STEP_RECORD_CHARS])
            steps.append(
                ToolCallRecord(
                    name=call.name,
                    arguments=call.arguments,
                    result=result[:MAX_STEP_RECORD_CHARS],
                )
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    messages.append({"role": "user", "content": FINAL_ANSWER_PROMPT})
    final = _chat(chat, tracer, messages, None)
    return _result(final.content, chat, steps)


def _chat(
    chat: llm.ChatClient,
    tracer: tracing.Tracer,
    messages: list[dict[str, Any]],
    tool_specs: list[dict[str, Any]] | None,
) -> llm.ChatResponse:
    with tracer.observe("chat", as_type="generation", input=messages, model=chat.model) as span:
        response = chat.chat(messages, tool_specs)
        span.update(
            output={
                "content": response.content,
                "tool_calls": [
                    {"name": call.name, "arguments": call.arguments} for call in response.tool_calls
                ],
            }
        )
        return response


def _assistant_message(response: llm.ChatResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": response.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in response.tool_calls
        ],
    }


def _result(
    content: str | None, chat: llm.ChatClient, steps: list[ToolCallRecord]
) -> Recommendation:
    answer = (content or "").strip() or FALLBACK_ANSWER
    return Recommendation(answer=answer, provider=chat.provider, model=chat.model, steps=steps)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))
