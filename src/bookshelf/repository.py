from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import date

from .models import AuthorCount, BookOut, ReadingStatus, ShelfCount, Stats

BOOK_COLUMNS = """
    b.id,
    b.goodreads_book_id,
    b.title,
    a.name AS author,
    b.isbn10,
    b.isbn13,
    b.publisher,
    b.binding,
    b.pages,
    b.year_published,
    b.original_year,
    b.average_rating,
    le.status,
    le.rating,
    le.date_read,
    le.date_added,
    le.read_count,
    le.shelves_raw,
    le.review
"""

BOOK_FROM = """
    FROM books AS b
    JOIN authors AS a ON a.id = b.author_id
    JOIN library_entries AS le ON le.book_id = b.id
"""


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _where(
    q: str | None,
    status: ReadingStatus | None,
    min_rating: int | None,
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        clauses.append("(b.title LIKE ? ESCAPE '\\' OR a.name LIKE ? ESCAPE '\\')")
        params.extend([pattern, pattern])
    if status is not None:
        clauses.append("le.status = ?")
        params.append(status.value)
    if min_rating is not None:
        clauses.append("le.rating >= ?")
        params.append(min_rating)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _row_to_book(row: sqlite3.Row) -> BookOut:
    return BookOut(
        id=row["id"],
        goodreads_book_id=row["goodreads_book_id"],
        title=row["title"],
        author=row["author"],
        isbn10=row["isbn10"],
        isbn13=row["isbn13"],
        publisher=row["publisher"],
        binding=row["binding"],
        pages=row["pages"],
        year_published=row["year_published"],
        original_year=row["original_year"],
        average_rating=row["average_rating"],
        status=ReadingStatus(row["status"]),
        rating=row["rating"],
        date_read=date.fromisoformat(row["date_read"]) if row["date_read"] else None,
        date_added=date.fromisoformat(row["date_added"]) if row["date_added"] else None,
        read_count=row["read_count"],
        shelves_raw=row["shelves_raw"],
        review=row["review"],
    )


def list_books(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    status: ReadingStatus | None = None,
    min_rating: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[BookOut], int]:
    where, params = _where(q, status, min_rating)

    total_row = conn.execute(f"SELECT COUNT(*) {BOOK_FROM} {where}", params).fetchone()
    total = int(total_row[0]) if total_row is not None else 0

    rows = conn.execute(
        f"""
        SELECT {BOOK_COLUMNS}
        {BOOK_FROM}
        {where}
        ORDER BY b.title COLLATE NOCASE
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return [_row_to_book(row) for row in rows], total


def get_book(conn: sqlite3.Connection, book_id: int) -> BookOut | None:
    row = conn.execute(
        f"SELECT {BOOK_COLUMNS} {BOOK_FROM} WHERE b.id = ?",
        (book_id,),
    ).fetchone()
    return _row_to_book(row) if row is not None else None


def get_stats(conn: sqlite3.Connection) -> Stats:
    total_row = conn.execute("SELECT COUNT(*) FROM library_entries").fetchone()
    total = int(total_row[0]) if total_row is not None else 0

    by_status = {status.value: 0 for status in ReadingStatus}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM library_entries GROUP BY status"):
        by_status[row["status"]] = int(row["n"])

    rating_counts = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "unrated": 0}
    rated_total = 0
    for row in conn.execute(
        "SELECT rating, COUNT(*) AS n FROM library_entries WHERE rating IS NOT NULL GROUP BY rating"
    ):
        rating_counts[str(row["rating"])] = int(row["n"])
        rated_total += int(row["n"])
    rating_counts["unrated"] = total - rated_total

    average_row = conn.execute("SELECT AVG(rating) FROM library_entries").fetchone()
    average_rating = (
        round(float(average_row[0]), 2)
        if average_row is not None and average_row[0] is not None
        else None
    )

    top_authors = [
        AuthorCount(name=row["name"], count=int(row["n"]))
        for row in conn.execute(
            """
            SELECT a.name, COUNT(*) AS n
            FROM books AS b
            JOIN authors AS a ON a.id = b.author_id
            GROUP BY a.id, a.name
            ORDER BY n DESC, a.name COLLATE NOCASE
            LIMIT 10
            """
        )
    ]

    shelf_counter: Counter[str] = Counter()
    for row in conn.execute(
        "SELECT shelves_raw FROM library_entries WHERE shelves_raw IS NOT NULL"
    ):
        for shelf in str(row["shelves_raw"]).split(","):
            name = shelf.strip()
            if name:
                shelf_counter[name] += 1
    top_shelves = [
        ShelfCount(name=name, count=count) for name, count in shelf_counter.most_common(10)
    ]

    return Stats(
        total_books=total,
        by_status=by_status,
        rating_counts=rating_counts,
        average_rating=average_rating,
        top_authors=top_authors,
        top_shelves=top_shelves,
    )
