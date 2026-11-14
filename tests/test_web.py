from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from bookshelf import openlibrary

FIND_DOCS = {
    "numFound": 2,
    "docs": [
        {
            "key": "/works/OL893415W",
            "title": "Dune",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 1965,
            "isbn": ["9780441013593"],
            "cover_i": 111,
            "edition_count": 100,
        },
        {
            "key": "/works/OL27258W",
            "title": "Neuromancer",
            "author_name": ["William Gibson"],
            "first_publish_year": 1984,
            "isbn": ["9780441013594"],
            "edition_count": 42,
        },
    ],
}


def fake_openlibrary(monkeypatch: pytest.MonkeyPatch, body: str | None = None) -> list[str]:
    payload = body if body is not None else json.dumps(FIND_DOCS)
    calls: list[str] = []

    def fake_fetch(
        query: str,
        *,
        limit: int,
        base_url: str = "",
        timeout: float = 0.0,
        transport: object = None,
    ) -> str:
        calls.append(query)
        return payload

    monkeypatch.setattr(openlibrary, "fetch_search", fake_fetch)
    return calls


def test_index_renders_empty_state(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>AI Bookshelf</h1>" in response.text
    assert "No books yet" in response.text
    assert 'href="/docs"' in response.text


def test_index_lists_imported_books(imported_client: TestClient) -> None:
    response = imported_client.get("/")

    assert response.status_code == 200
    assert "Showing 5 of 5 books" in response.text
    assert "Dune" in response.text
    assert "Ursula K. Le Guin" in response.text
    assert '<span class="pill read">Read</span>' in response.text
    assert "science-fiction" in response.text


def test_index_filters_by_status(imported_client: TestClient) -> None:
    response = imported_client.get("/", params={"status": "to_read"})

    assert response.status_code == 200
    assert "Showing 1 of 1 book" in response.text
    assert "Dune" in response.text
    assert "Piranesi" not in response.text
    assert '<option value="to_read" selected>' in response.text


def test_index_filters_by_search(imported_client: TestClient) -> None:
    response = imported_client.get("/", params={"q": "le guin"})

    assert response.status_code == 200
    assert "Showing 2 of 2 books" in response.text
    assert "The Dispossessed" in response.text
    assert "Dune" not in response.text
    assert 'value="le guin"' in response.text


def test_index_reports_no_matches(imported_client: TestClient) -> None:
    response = imported_client.get("/", params={"q": "tolkien"})

    assert response.status_code == 200
    assert "No books match those filters." in response.text
    assert '<a class="reset" href="/">Reset</a>' in response.text


def test_index_escapes_book_fields(conn: sqlite3.Connection, client: TestClient) -> None:
    conn.execute(
        "INSERT INTO authors (name, normalized_name) VALUES (?, ?)",
        ("<em>Ann</em> Author", "ann author"),
    )
    author_id = conn.execute(
        "SELECT id FROM authors WHERE normalized_name = ?", ("ann author",)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO books (goodreads_book_id, title, author_id) VALUES (?, ?, ?)",
        ("9999", "<script>alert(1)</script>", author_id),
    )
    book_id = conn.execute(
        "SELECT id FROM books WHERE goodreads_book_id = ?", ("9999",)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO library_entries (book_id, status, review) VALUES (?, 'read', ?)",
        (book_id, "Review with <b>markup</b>"),
    )
    conn.commit()

    response = client.get("/")

    assert response.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;em&gt;Ann&lt;/em&gt; Author" in response.text
    assert "Review with &lt;b&gt;markup&lt;/b&gt;" in response.text


def test_index_rejects_long_search(imported_client: TestClient) -> None:
    response = imported_client.get("/", params={"q": "x" * 201})

    assert response.status_code == 422


def test_find_page_prompts_without_query(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake_openlibrary(monkeypatch)

    response = client.get("/find")

    assert response.status_code == 200
    assert "Search Open Library for books" in response.text
    assert calls == []
    assert '<a href="/find" aria-current="page">Find books</a>' in response.text


def test_find_page_shows_new_books_and_hides_owned(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_openlibrary(monkeypatch)

    response = imported_client.get("/find", params={"q": "dune"})

    assert response.status_code == 200
    assert "Neuromancer" in response.text
    assert "William Gibson" in response.text
    assert "https://openlibrary.org/works/OL27258W" in response.text
    assert "2 found · 1 already in your library · fresh" in response.text

    # Dune is already on the shelf, so it must not appear as a fresh card.
    assert 'href="https://openlibrary.org/works/OL893415W"' not in response.text


def test_find_page_survives_upstream_failure(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_fetch(*args: object, **kwargs: object) -> str:
        raise openlibrary.OpenLibraryError("offline")

    monkeypatch.setattr(openlibrary, "fetch_search", failing_fetch)

    response = imported_client.get("/find", params={"q": "dune"})

    assert response.status_code == 200
    assert "Open Library could not be reached" in response.text
