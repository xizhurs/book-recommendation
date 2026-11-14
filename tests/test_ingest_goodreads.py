from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from bookshelf.ingest.goodreads import import_goodreads


def test_import_report_counts(conn: sqlite3.Connection, sample_csv: Path) -> None:
    report = import_goodreads(conn, sample_csv)

    assert report.rows_seen == 6
    assert report.inserted == 5
    assert report.updated == 0
    assert report.skipped == 1
    assert report.errors == 0


def test_import_normalizes_fields(conn: sqlite3.Connection, sample_csv: Path) -> None:
    import_goodreads(conn, sample_csv)

    row = conn.execute(
        """
        SELECT b.title, a.name AS author, b.isbn10, b.isbn13, b.pages,
               le.status, le.rating, le.date_read, le.read_count, le.shelves_raw
        FROM books AS b
        JOIN authors AS a ON a.id = b.author_id
        JOIN library_entries AS le ON le.book_id = b.id
        WHERE b.goodreads_book_id = '1'
        """
    ).fetchone()

    assert row is not None
    assert row["title"] == "The Left Hand of Darkness"
    assert row["author"] == "Ursula K. Le Guin"
    assert row["isbn10"] == "0441478125"
    assert row["isbn13"] == "9780441478125"
    assert row["pages"] == 304
    assert row["status"] == "read"
    assert row["rating"] == 5
    assert row["date_read"] == "2024-01-15"
    assert row["read_count"] == 2
    assert row["shelves_raw"] == "science-fiction, favorites"


def test_unrated_and_missing_values_become_null(conn: sqlite3.Connection, sample_csv: Path) -> None:
    import_goodreads(conn, sample_csv)

    row = conn.execute(
        """
        SELECT b.isbn10, b.isbn13, le.rating, le.date_read
        FROM books AS b
        JOIN library_entries AS le ON le.book_id = b.id
        WHERE b.goodreads_book_id = '3'
        """
    ).fetchone()

    assert row is not None
    assert row["isbn10"] is None
    assert row["isbn13"] is None
    assert row["rating"] is None
    assert row["date_read"] is None


def test_import_is_idempotent(conn: sqlite3.Connection, sample_csv: Path) -> None:
    first = import_goodreads(conn, sample_csv)
    second = import_goodreads(conn, sample_csv)

    assert first.inserted == 5
    assert second.inserted == 0
    assert second.updated == 5
    assert second.skipped == 1

    books = conn.execute("SELECT COUNT(*) FROM books").fetchone()
    entries = conn.execute("SELECT COUNT(*) FROM library_entries").fetchone()
    assert books is not None and books[0] == 5
    assert entries is not None and entries[0] == 5


def test_duplicate_authors_are_merged(conn: sqlite3.Connection, sample_csv: Path) -> None:
    import_goodreads(conn, sample_csv)

    row = conn.execute("SELECT COUNT(*) FROM authors").fetchone()
    assert row is not None and row[0] == 4


def test_reviews_are_opt_in(conn: sqlite3.Connection, sample_csv: Path) -> None:
    import_goodreads(conn, sample_csv)

    row = conn.execute(
        """
        SELECT le.review
        FROM library_entries AS le
        JOIN books AS b ON b.id = le.book_id
        WHERE b.goodreads_book_id = '1'
        """
    ).fetchone()
    assert row is not None
    assert row["review"] is None


def test_reviews_import_when_requested(conn: sqlite3.Connection, sample_csv: Path) -> None:
    import_goodreads(conn, sample_csv, include_reviews=True)

    row = conn.execute(
        """
        SELECT le.review
        FROM library_entries AS le
        JOIN books AS b ON b.id = le.book_id
        WHERE b.goodreads_book_id = '1'
        """
    ).fetchone()
    assert row is not None
    assert row["review"] == "A favorite, read twice."


def test_reimport_without_reviews_preserves_existing_review(
    conn: sqlite3.Connection, sample_csv: Path
) -> None:
    import_goodreads(conn, sample_csv, include_reviews=True)
    import_goodreads(conn, sample_csv)

    row = conn.execute(
        """
        SELECT le.review
        FROM library_entries AS le
        JOIN books AS b ON b.id = le.book_id
        WHERE b.goodreads_book_id = '1'
        """
    ).fetchone()
    assert row is not None
    assert row["review"] == "A favorite, read twice."


def test_unknown_status_is_reported(conn: sqlite3.Connection, tmp_path: Path) -> None:
    bad_csv = tmp_path / "bad.csv"
    with bad_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Book Id", "Title", "Author", "Exclusive Shelf"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Book Id": "99",
                "Title": "Unknown Shelf",
                "Author": "Nobody",
                "Exclusive Shelf": "someday",
            }
        )

    report = import_goodreads(conn, bad_csv)

    assert report.rows_seen == 1
    assert report.inserted == 0
    assert report.errors == 1
    assert report.error_details[0].row == 2
    assert "unknown Exclusive Shelf" in report.error_details[0].message


def test_missing_required_columns_fails(conn: sqlite3.Connection, tmp_path: Path) -> None:
    bad_csv = tmp_path / "missing_columns.csv"
    bad_csv.write_text("Book Id,Title\n1,No Author\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        import_goodreads(conn, bad_csv)
