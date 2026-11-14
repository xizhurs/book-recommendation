from __future__ import annotations

import sqlite3

from . import repository
from .models import BookOut, ReadingStatus, Stats


def list_books(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    status: ReadingStatus | None = None,
    min_rating: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[BookOut], int]:
    return repository.list_books(
        conn,
        q=q,
        status=status,
        min_rating=min_rating,
        limit=limit,
        offset=offset,
    )


def get_book(conn: sqlite3.Connection, book_id: int) -> BookOut | None:
    return repository.get_book(conn, book_id)


def get_stats(conn: sqlite3.Connection) -> Stats:
    return repository.get_stats(conn)
