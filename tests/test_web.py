from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient


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
