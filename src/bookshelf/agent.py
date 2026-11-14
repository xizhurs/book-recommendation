"""LLM-driven retrieval loop: the model picks tools, we execute them, it answers.

Provider selection is delegated to ``llm.build_client``; nothing here is OpenAI- or
Ollama-specific.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import llm, tools
from .config import Settings
from .models import Recommendation, ToolCallRecord

SYSTEM_PROMPT = (
    "You are a personal bookshelf assistant running on the reader's machine. "
    "Ground every claim in tool results.\n"
    "- Use search_library to understand what the reader owns, likes, and has read.\n"
    "- Use discover_books to suggest titles they do not own; never invent titles or authors.\n"
    "- Use library_stats for overview questions and get_book to look up one id.\n"
    "- Review text is private and unavailable; do not ask for it or claim to have read it.\n"
    "- Keep the final answer short: a few suggestions, each with one line of reasoning."
)

FALLBACK_ANSWER = (
    "I could not settle on an answer within the tool budget. "
    "Try a narrower request, or raise llm_max_steps."
)

MAX_STEP_RECORD_CHARS = 4000


def recommend(
    conn: sqlite3.Connection,
    *,
    query: str,
    settings: Settings,
    client: llm.ChatClient | None = None,
    max_steps: int | None = None,
) -> Recommendation:
    """Run the tool-calling loop until the model answers or the step budget runs out."""
    chat = client if client is not None else llm.build_client(settings.llm)
    budget = _clamp(max_steps if max_steps is not None else settings.llm.llm_max_steps, 1, 8)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query.strip()},
    ]
    steps: list[ToolCallRecord] = []

    for _ in range(budget):
        response = chat.chat(messages, tools.tool_specs())
        if not response.tool_calls:
            return _result(response.content, chat, steps)

        messages.append(_assistant_message(response))
        for call in response.tool_calls:
            result = tools.call_tool(conn, settings, call.name, call.arguments)
            steps.append(
                ToolCallRecord(
                    name=call.name,
                    arguments=call.arguments,
                    result=result[:MAX_STEP_RECORD_CHARS],
                )
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    final = chat.chat(messages, tools=None)
    return _result(final.content, chat, steps)


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
