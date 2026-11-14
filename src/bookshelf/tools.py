"""Tools the LLM can call. Each handler is a thin adapter over services/repository.

Tool results are compact JSON strings: they are fed back to the model, so they must stay
small, and they must never include review text (that is private and would leave the machine
in hosted-API mode).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import rerank
from .config import Settings
from .models import BookOut, ReadingStatus
from .services import discover, fuzzy_search_books, get_book, get_stats, list_books

MAX_SEARCH_LIMIT = 25
MAX_DISCOVER_LIMIT = 15

# Shared by the built-in agent's system prompt and the MCP server instructions, so every client
# gets the same guidance on using these tools.
TASTE_GUIDANCE = (
    "For open-ended requests ('what should I read', 'based on what I read') first learn the "
    "reader's taste: search_library with min_rating 4 for favourites, status read for recent "
    "reads, and library_stats for favourite authors. Base the suggestions on what you find and "
    "name the owned books each one follows from. For narrow requests, search only what is "
    "relevant."
)
DISCOVERY_GUIDANCE = (
    "discover_books is a plain keyword search with no notion of 'similar to'; topic or genre "
    "queries return noise (essays, biographies, unrelated classics). To recommend new books, "
    "name specific candidates from your own knowledge of similar books, then confirm each with "
    "discover_books using its exact title and author. Recommend only books that search "
    "confirmed exist and are not already owned; say so if none could be confirmed."
)

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_library",
            "description": (
                "Search the reader's own library by title or author. Use it to learn their "
                "taste, find read books, or check whether a title is already owned."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Title or author text."},
                    "status": {
                        "type": "string",
                        "enum": ["read", "currently_reading", "to_read"],
                        "description": "Only return books with this reading status.",
                    },
                    "min_rating": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Only return books rated at least this many stars.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                        "description": "Maximum books to return (default 10).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "library_stats",
            "description": (
                "Summarize the library: counts by status, rating histogram, average rating, "
                "top authors, and top shelves."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discover_books",
            "description": (
                "Search Open Library for books the reader does not own yet. Use this for "
                "recommendations and new suggestions; results are deduped against the library."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Keyword search, not 'similar to'. Works best with an exact title "
                            "and author (e.g. 'Bridget Jones's Diary Helen Fielding') to confirm "
                            "a book exists; topic or genre queries return mostly noise."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_DISCOVER_LIMIT,
                        "description": "Maximum candidates to return (default 8).",
                    },
                    "include_owned": {
                        "type": "boolean",
                        "description": "Also return books already in the library.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_book",
            "description": "Fetch one library book by its numeric id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer", "minimum": 1, "description": "Library book id."}
                },
                "required": ["book_id"],
            },
        },
    },
]


def tool_specs() -> list[dict[str, Any]]:
    return TOOL_SPECS


def call_tool(
    conn: sqlite3.Connection,
    settings: Settings,
    name: str,
    arguments: dict[str, Any],
) -> str:
    """Dispatch a tool call, returning JSON. Tool failures are reported, not raised."""
    handlers = {
        "search_library": _search_library,
        "library_stats": _library_stats,
        "discover_books": _discover_books,
        "get_book": _get_book,
    }
    handler = handlers.get(name)
    if handler is None:
        return json.dumps({"error": f"unknown tool: {name}"})
    try:
        return json.dumps(handler(conn, settings, arguments), ensure_ascii=False)
    except Exception as exc:  # tool errors go back to the model so it can recover
        return json.dumps({"error": str(exc)})


def _search_library(
    conn: sqlite3.Connection, settings: Settings, arguments: dict[str, Any]
) -> dict[str, Any]:
    status = _status_argument(arguments.get("status"))
    min_rating = _int_argument(arguments.get("min_rating"), default=None)
    if min_rating is not None:
        min_rating = max(1, min(5, min_rating))
    limit = _int_argument(arguments.get("limit"), default=10) or 10
    limit = max(1, min(MAX_SEARCH_LIMIT, limit))

    query = _str_argument(arguments.get("query"))
    books, total = list_books(
        conn,
        q=query,
        status=status,
        min_rating=min_rating,
        limit=limit,
    )
    if total == 0 and query:
        similar = fuzzy_search_books(
            conn, q=query, status=status, min_rating=min_rating, limit=limit
        )
        if similar:
            return {
                "total": len(similar),
                "books": [_book_summary(book) for book in similar],
                "fuzzy": True,
                "note": f"No exact match for {query!r}; these are the closest spellings.",
            }
    return {"total": total, "books": [_book_summary(book) for book in books]}


def _library_stats(
    conn: sqlite3.Connection, settings: Settings, arguments: dict[str, Any]
) -> dict[str, Any]:
    return get_stats(conn).model_dump(mode="json")


def _discover_books(
    conn: sqlite3.Connection, settings: Settings, arguments: dict[str, Any]
) -> dict[str, Any]:
    query = _str_argument(arguments.get("query"))
    if not query:
        raise ValueError("query is required")
    limit = _int_argument(arguments.get("limit"), default=8) or 8
    limit = max(1, min(MAX_DISCOVER_LIMIT, limit))
    scorer = rerank.get_scorer(settings.rerank_model) if settings.rerank_enabled else None
    page = discover(
        conn,
        query=query,
        limit=limit,
        include_owned=_bool_argument(arguments.get("include_owned")),
        settings=settings,
        scorer=scorer,
    )
    return {
        "total_found": page.total_found,
        "skipped_owned": page.skipped_owned,
        "cached": page.cached,
        "reranked": page.reranked,
        "books": [
            {
                "openlibrary_key": item.openlibrary_key,
                "title": item.title,
                "author": item.author,
                "first_publish_year": item.first_publish_year,
                "isbn13": item.isbn13,
                "in_library": item.in_library,
            }
            for item in page.items
        ],
    }


def _get_book(
    conn: sqlite3.Connection, settings: Settings, arguments: dict[str, Any]
) -> dict[str, Any]:
    book_id = _int_argument(arguments.get("book_id"), default=None)
    if book_id is None:
        raise ValueError("book_id is required")
    book = get_book(conn, book_id)
    if book is None:
        raise ValueError(f"no book with id {book_id}")
    return _book_summary(book)


def _book_summary(book: BookOut) -> dict[str, Any]:
    shelves = [shelf.strip() for shelf in (book.shelves_raw or "").split(",") if shelf.strip()]
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "status": book.status.value,
        "rating": book.rating,
        "date_read": book.date_read.isoformat() if book.date_read else None,
        "year_published": book.year_published,
        "pages": book.pages,
        "shelves": shelves,
        "has_review": bool(book.review),
    }


def _status_argument(value: object) -> ReadingStatus | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return ReadingStatus(normalized)
    except ValueError as exc:
        allowed = ", ".join(status.value for status in ReadingStatus)
        raise ValueError(f"unknown status {value!r}; use one of: {allowed}") from exc


def _str_argument(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int_argument(value: object, *, default: int | None) -> int | None:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _bool_argument(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False
