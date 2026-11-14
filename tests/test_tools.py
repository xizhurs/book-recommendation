from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from bookshelf import tools
from bookshelf.config import Settings
from bookshelf.ingest.goodreads import import_goodreads
from bookshelf.models import DiscoveryItem, DiscoveryPage


@pytest.fixture
def library(conn: sqlite3.Connection, sample_csv: Path) -> sqlite3.Connection:
    import_goodreads(conn, sample_csv, include_reviews=True)
    return conn


@pytest.fixture
def settings() -> Settings:
    return Settings(rerank_enabled=False)


def call(
    conn: sqlite3.Connection, settings: Settings, name: str, arguments: dict[str, object]
) -> dict[str, object]:
    return json.loads(tools.call_tool(conn, settings, name, arguments))


def test_tool_specs_expose_the_four_tools() -> None:
    names = [spec["function"]["name"] for spec in tools.tool_specs()]

    assert names == ["search_library", "library_stats", "discover_books", "get_book"]


def test_search_library_returns_summaries_without_review_text(
    library: sqlite3.Connection, settings: Settings
) -> None:
    payload = call(library, settings, "search_library", {"query": "ursula"})

    assert payload["total"] == 2
    books = payload["books"]
    assert {book["title"] for book in books} == {
        "The Left Hand of Darkness",
        "The Dispossessed",
    }
    first = next(book for book in books if book["title"] == "The Left Hand of Darkness")
    assert first["status"] == "read"
    assert first["rating"] == 5
    assert first["shelves"] == ["science-fiction", "favorites"]
    assert first["has_review"] is True
    assert "review" not in first
    assert "A favorite, read twice." not in json.dumps(payload)


def test_search_library_filters_by_status_and_rating(
    library: sqlite3.Connection, settings: Settings
) -> None:
    to_read = call(library, settings, "search_library", {"status": "to_read"})
    five_star = call(library, settings, "search_library", {"min_rating": 5})

    assert [book["title"] for book in to_read["books"]] == ["Dune"]
    assert [book["title"] for book in five_star["books"]] == ["The Left Hand of Darkness"]


def test_search_library_rejects_unknown_status(
    library: sqlite3.Connection, settings: Settings
) -> None:
    payload = call(library, settings, "search_library", {"status": "abandoned"})

    assert "unknown status" in payload["error"]


def test_search_library_clamps_limit(library: sqlite3.Connection, settings: Settings) -> None:
    payload = call(library, settings, "search_library", {"limit": 999})

    assert len(payload["books"]) == 5


def test_library_stats_returns_counts(library: sqlite3.Connection, settings: Settings) -> None:
    payload = call(library, settings, "library_stats", {})

    assert payload["total_books"] == 5
    assert payload["by_status"]["read"] == 3
    assert payload["top_authors"][0] == {"name": "Ursula K. Le Guin", "count": 2}


def test_get_book_accepts_string_ids(library: sqlite3.Connection, settings: Settings) -> None:
    payload = call(library, settings, "get_book", {"book_id": "2"})

    assert payload["title"] == "Piranesi"
    assert payload["author"] == "Susanna Clarke"


def test_get_book_reports_missing_id(library: sqlite3.Connection, settings: Settings) -> None:
    assert "no book with id 99" in call(library, settings, "get_book", {"book_id": 99})["error"]


def test_unknown_tool_is_reported(settings: Settings, conn: sqlite3.Connection) -> None:
    payload = call(conn, settings, "delete_everything", {})

    assert payload == {"error": "unknown tool: delete_everything"}


def test_discover_books_delegates_to_the_service(
    conn: sqlite3.Connection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_discover(
        connection: sqlite3.Connection,
        *,
        query: str,
        limit: int,
        include_owned: bool,
        settings: Settings,
        scorer: object = None,
    ) -> DiscoveryPage:
        captured.update(query=query, limit=limit, include_owned=include_owned, scorer=scorer)
        return DiscoveryPage(
            query=query,
            items=[
                DiscoveryItem(
                    openlibrary_key="/works/OL1W",
                    title="A New Book",
                    author="Someone",
                    first_publish_year=2024,
                    in_library=False,
                )
            ],
            total_found=1,
            skipped_owned=0,
            cached=False,
            requests_used=1,
            reranked=False,
        )

    monkeypatch.setattr(tools, "discover", fake_discover)

    payload = call(
        conn, settings, "discover_books", {"query": "new", "limit": 3, "include_owned": True}
    )

    assert captured == {"query": "new", "limit": 3, "include_owned": True, "scorer": None}
    assert payload["books"] == [
        {
            "openlibrary_key": "/works/OL1W",
            "title": "A New Book",
            "author": "Someone",
            "first_publish_year": 2024,
            "isbn13": None,
            "in_library": False,
        }
    ]


def test_discover_books_requires_a_query(conn: sqlite3.Connection, settings: Settings) -> None:
    assert "query is required" in call(conn, settings, "discover_books", {})["error"]
