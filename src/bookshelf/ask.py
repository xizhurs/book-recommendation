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

from . import agent, llm
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

    settings = Settings()
    if args.no_rerank:
        settings.rerank_enabled = False
    db_path = args.db if args.db is not None else settings.db_path

    try:
        with closing(connect(db_path)) as conn:
            init_db(conn)
            result = agent.recommend(
                conn,
                query=query,
                settings=settings,
                max_steps=args.max_steps,
            )
    except llm.LLMError as exc:
        print(f"LLM request failed: {exc}", file=sys.stderr)
        return 1

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
