"""Ask the bookshelf agent from the command line.

    uv run python -m bookshelf.ask "What should I read after Dune?"

Runs the same ``agent.recommend`` loop as ``POST /recommend`` and the ``/ask`` page, using the
provider configured by ``LLM_PROVIDER``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from . import agent, llm, tracing
from .config import Settings
from .db import connect, init_db
from .models import Recommendation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookshelf.ask",
        description="Ask the bookshelf agent for a recommendation grounded in your library.",
    )
    parser.add_argument("query", nargs="+", help="Question, e.g. what should I read after Dune?")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite database path (default: BOOKSHELF_DB_PATH)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Model turns before the final answer, 1-8 (default: LLM_MAX_STEPS)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name for the configured provider (default: OLLAMA_MODEL / OPENAI_MODEL)",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Langfuse session id to group related questions (ignored when tracing is off)",
    )
    parser.add_argument(
        "--steps",
        action="store_true",
        help="Print each tool call and its result before the answer",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="Skip local reranking in discovery tool calls",
    )
    parser.add_argument("--json", action="store_true", help="Print the full response as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_steps is not None and not 1 <= args.max_steps <= 8:
        print("--max-steps must be between 1 and 8", file=sys.stderr)
        return 2

    query = " ".join(args.query).strip()
    if not query:
        print("Question cannot be empty", file=sys.stderr)
        return 2

    session_id = args.session_id.strip() if args.session_id is not None else None
    if session_id is not None and not (
        0 < len(session_id) <= 200 and all(" " <= c <= "~" for c in session_id)
    ):
        print("--session-id must be 1-200 printable ASCII characters", file=sys.stderr)
        return 2

    model = None
    if args.model is not None:
        model = args.model.strip()
        if not model:
            print("--model cannot be empty", file=sys.stderr)
            return 2
    settings = Settings().with_overrides(model=model, rerank=False if args.no_rerank else None)
    db_path = args.db if args.db is not None else settings.db_path

    try:
        with closing(connect(db_path)) as conn:
            init_db(conn)
            result = agent.recommend(
                conn,
                query=query,
                settings=settings,
                max_steps=args.max_steps,
                session_id=session_id,
            )
    except llm.LLMError as exc:
        print(f"LLM request failed: {exc}", file=sys.stderr)
        return 1
    finally:
        tracing.flush(settings.tracing)

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        _print_result(result, show_steps=args.steps)
    return 0


def _print_result(result: Recommendation, *, show_steps: bool) -> None:
    if show_steps and result.steps:
        for position, step in enumerate(result.steps, start=1):
            arguments = json.dumps(step.arguments, ensure_ascii=False)
            print(f"[{position}] {step.name} {arguments}")
            print(step.result)
        print()

    print(result.answer)
    calls = "tool call" if len(result.steps) == 1 else "tool calls"
    print(f"\n{result.provider} · {result.model} · {len(result.steps)} {calls}")


if __name__ == "__main__":
    raise SystemExit(main())
