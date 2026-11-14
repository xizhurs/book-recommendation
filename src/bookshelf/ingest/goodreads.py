from __future__ import annotations

import argparse
import csv
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import Settings
from ..db import connect, init_db
from ..models import ReadingStatus

STATUS_MAP = {
    "read": ReadingStatus.READ,
    "currently-reading": ReadingStatus.CURRENTLY_READING,
    "to-read": ReadingStatus.TO_READ,
}
REQUIRED_COLUMNS = ("Book Id", "Title", "Author", "Exclusive Shelf")


class RowError(BaseModel):
    row: int
    message: str


class ImportReport(BaseModel):
    source_file: str
    rows_seen: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[RowError] = Field(default_factory=list)


@dataclass(frozen=True)
class ParsedRow:
    goodreads_book_id: str
    title: str
    author: str
    isbn10: str | None
    isbn13: str | None
    rating: int | None
    average_rating: float | None
    publisher: str | None
    binding: str | None
    pages: int | None
    year_published: int | None
    original_year: int | None
    date_read: str | None
    date_added: str | None
    shelves_raw: str | None
    status: ReadingStatus
    review: str | None
    read_count: int


def _clean(value: str | None) -> str | None:
    """Strip whitespace and Excel-style =\"...\" wrappers used by Goodreads."""
    if value is None:
        return None
    text = value.strip()
    if len(text) >= 3 and text.startswith('="') and text.endswith('"'):
        text = text[2:-1]
    text = text.strip()
    return text or None


def _parse_isbn(value: str | None) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    text = text.lstrip("=").replace("-", "").replace(" ", "")
    return text if len(text) in (10, 13) else None


def _parse_int(value: str | None) -> int | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return int(float(text.replace(",", "")))
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _parse_date(value: str | None) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_rating(value: str | None) -> int | None:
    rating = _parse_int(value)
    if rating is None or rating < 1 or rating > 5:
        return None
    return rating


def _parse_status(value: str | None) -> ReadingStatus:
    shelf = _clean(value)
    if shelf is None:
        raise ValueError("missing Exclusive Shelf")
    try:
        return STATUS_MAP[shelf]
    except KeyError as exc:
        raise ValueError(f"unknown Exclusive Shelf: {shelf!r}") from exc


def _parse_row(raw: Mapping[str, str | None], *, include_reviews: bool) -> ParsedRow:
    book_id = _clean(raw.get("Book Id"))
    title = _clean(raw.get("Title"))
    author = _clean(raw.get("Author"))
    if book_id is None:
        raise ValueError("missing Book Id")
    if title is None:
        raise ValueError("missing Title")
    if author is None:
        raise ValueError("missing Author")

    return ParsedRow(
        goodreads_book_id=book_id,
        title=title,
        author=author,
        isbn10=_parse_isbn(raw.get("ISBN")),
        isbn13=_parse_isbn(raw.get("ISBN13")),
        rating=_parse_rating(raw.get("My Rating")),
        average_rating=_parse_float(raw.get("Average Rating")),
        publisher=_clean(raw.get("Publisher")),
        binding=_clean(raw.get("Binding")),
        pages=_parse_int(raw.get("Number of Pages")),
        year_published=_parse_int(raw.get("Year Published")),
        original_year=_parse_int(raw.get("Original Publication Year")),
        date_read=_parse_date(raw.get("Date Read")),
        date_added=_parse_date(raw.get("Date Added")),
        shelves_raw=_clean(raw.get("Bookshelves")),
        status=_parse_status(raw.get("Exclusive Shelf")),
        review=_clean(raw.get("My Review")) if include_reviews else None,
        read_count=_parse_int(raw.get("Read Count")) or 0,
    )


def _start_import_run(conn: sqlite3.Connection, source_file: str) -> int:
    cursor = conn.execute(
        """
        INSERT INTO import_runs (source_file, started_at, status)
        VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 'running')
        """,
        (source_file,),
    )
    conn.commit()
    if cursor.lastrowid is None:
        raise RuntimeError("failed to create import run")
    return int(cursor.lastrowid)


def _finish_import_run(
    conn: sqlite3.Connection,
    run_id: int,
    report: ImportReport,
    *,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE import_runs
        SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            status = ?,
            inserted = ?,
            updated = ?,
            skipped = ?,
            errors = ?
        WHERE id = ?
        """,
        (
            status,
            report.inserted,
            report.updated,
            report.skipped,
            report.errors,
            run_id,
        ),
    )
    conn.commit()


def _get_or_create_author(conn: sqlite3.Connection, author: str) -> int:
    normalized = " ".join(author.casefold().split())
    conn.execute(
        """
        INSERT INTO authors (name, normalized_name)
        VALUES (?, ?)
        ON CONFLICT (normalized_name) DO NOTHING
        """,
        (author, normalized),
    )
    row = conn.execute(
        "SELECT id FROM authors WHERE normalized_name = ?",
        (normalized,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"failed to resolve author {author!r}")
    return int(row["id"])


def _upsert_book(conn: sqlite3.Connection, row: ParsedRow, author_id: int) -> int:
    conn.execute(
        """
        INSERT INTO books (
            goodreads_book_id, title, author_id, isbn10, isbn13, publisher, binding,
            pages, year_published, original_year, average_rating
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (goodreads_book_id) DO UPDATE SET
            title = excluded.title,
            author_id = excluded.author_id,
            isbn10 = excluded.isbn10,
            isbn13 = excluded.isbn13,
            publisher = excluded.publisher,
            binding = excluded.binding,
            pages = excluded.pages,
            year_published = excluded.year_published,
            original_year = excluded.original_year,
            average_rating = excluded.average_rating,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            row.goodreads_book_id,
            row.title,
            author_id,
            row.isbn10,
            row.isbn13,
            row.publisher,
            row.binding,
            row.pages,
            row.year_published,
            row.original_year,
            row.average_rating,
        ),
    )
    book = conn.execute(
        "SELECT id FROM books WHERE goodreads_book_id = ?",
        (row.goodreads_book_id,),
    ).fetchone()
    if book is None:
        raise RuntimeError(f"failed to resolve book {row.goodreads_book_id!r}")
    return int(book["id"])


def _upsert_library_entry(conn: sqlite3.Connection, book_id: int, row: ParsedRow) -> None:
    conn.execute(
        """
        INSERT INTO library_entries (
            book_id, status, rating, date_read, date_added, read_count, shelves_raw, review
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (book_id) DO UPDATE SET
            status = excluded.status,
            rating = excluded.rating,
            date_read = excluded.date_read,
            date_added = excluded.date_added,
            read_count = excluded.read_count,
            shelves_raw = excluded.shelves_raw,
            review = COALESCE(excluded.review, library_entries.review),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            book_id,
            row.status.value,
            row.rating,
            row.date_read,
            row.date_added,
            row.read_count,
            row.shelves_raw,
            row.review,
        ),
    )


def import_goodreads(
    conn: sqlite3.Connection,
    csv_path: Path | str,
    *,
    include_reviews: bool = False,
) -> ImportReport:
    """Import a Goodreads CSV export. Re-running is idempotent by Book Id."""
    source = Path(csv_path)
    report = ImportReport(source_file=source.name)
    run_id = _start_import_run(conn, source.name)
    seen: set[str] = set()

    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
            if missing:
                raise ValueError(f"missing required columns: {', '.join(missing)}")

            with conn:
                for line_number, raw in enumerate(reader, start=2):
                    report.rows_seen += 1
                    try:
                        row = _parse_row(raw, include_reviews=include_reviews)
                    except ValueError as exc:
                        report.errors += 1
                        report.error_details.append(RowError(row=line_number, message=str(exc)))
                        continue

                    if row.goodreads_book_id in seen:
                        report.skipped += 1
                        continue
                    seen.add(row.goodreads_book_id)

                    existing = conn.execute(
                        "SELECT id FROM books WHERE goodreads_book_id = ?",
                        (row.goodreads_book_id,),
                    ).fetchone()
                    author_id = _get_or_create_author(conn, row.author)
                    book_id = _upsert_book(conn, row, author_id)
                    _upsert_library_entry(conn, book_id, row)

                    if existing is None:
                        report.inserted += 1
                    else:
                        report.updated += 1
    except Exception:
        _finish_import_run(conn, run_id, report, status="failed")
        raise

    _finish_import_run(conn, run_id, report, status="completed")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a Goodreads CSV export into the local SQLite database."
    )
    parser.add_argument("csv_path", type=Path, help="Path to goodreads_library_export.csv")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite database path (default: BOOKSHELF_DB_PATH)",
    )
    parser.add_argument(
        "--include-reviews",
        action="store_true",
        help="Import My Review text. Off by default to limit personal data.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    db_path = args.db if args.db is not None else settings.db_path

    with closing(connect(db_path)) as conn:
        init_db(conn)
        report = import_goodreads(conn, args.csv_path, include_reviews=args.include_reviews)

    print(report.model_dump_json(indent=2))
    return 0 if report.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
