"""Discover books through Open Library from the command line.

    uv run python -m bookshelf.discover "dune frank herbert" --limit 5

Uses the same service layer as the API, including caching, dedupe, and local reranking.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from . import openlibrary, rerank
from .config import Settings
from .db import connect, init_db
from .models import DiscoveryPage
from .services import discover


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookshelf.discover",
        description="Search Open Library, skipping books already in your library.",
    )
    parser.add_argument("query", nargs="+", help="Search text, e.g. dune frank herbert")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite database path (default: BOOKSHELF_DB_PATH)",
    )
    parser.add_argument("--limit", type=int, default=5, help="Results to print (1-25, default 5)")
    parser.add_argument(
        "--include-owned",
        action="store_true",
        help="Also show books already in your library",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="Keep Open Library's order instead of reranking locally",
    )
    parser.add_argument("--json", action="store_true", help="Print the full response as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.limit <= 25:
        print("--limit must be between 1 and 25", file=sys.stderr)
        return 2

    query = " ".join(args.query).strip()
    if not query:
        print("Search text cannot be empty", file=sys.stderr)
        return 2

    settings = Settings()
    db_path = args.db if args.db is not None else settings.db_path
    scorer = None
    if settings.rerank_enabled and not args.no_rerank:
        scorer = rerank.get_scorer(settings.rerank_model)

    try:
        with closing(connect(db_path)) as conn:
            init_db(conn)
            page = discover(
                conn,
                query=query,
                limit=args.limit,
                include_owned=args.include_owned,
                settings=settings,
                scorer=scorer,
            )
    except openlibrary.OpenLibraryError as exc:
        print(f"Open Library request failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(page.model_dump_json(indent=2))
    else:
        _print_page(page)
    return 0


def _print_page(page: DiscoveryPage) -> None:
    if not page.items:
        print("No books found.")
    for position, item in enumerate(page.items, start=1):
        details = [item.title]
        if item.author:
            details.append(f"by {item.author}")
        if item.first_publish_year is not None:
            details.append(f"({item.first_publish_year})")
        if item.in_library:
            details.append("[in library]")
        print(f"{position}. {' '.join(details)}")

    source = "cached" if page.cached else "fresh"
    summary = f"{len(page.items)} of {page.total_found} results · {source}"
    if page.skipped_owned:
        summary += f" · {page.skipped_owned} already in your library"
    if page.reranked:
        summary += " · reranked"
    print(f"\n{summary}")


if __name__ == "__main__":
    raise SystemExit(main())
