from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from .. import web
from ..db import schema_version
from ..models import BookOut, BookPage, HealthResponse, ReadingStatus, Stats
from ..services import get_book as get_book_service
from ..services import get_stats as get_stats_service
from ..services import list_books as list_books_service
from .deps import get_db

DbConn = Annotated[sqlite3.Connection, Depends(get_db)]

router = APIRouter()
books_router = APIRouter(prefix="/books", tags=["books"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(
    conn: DbConn,
    q: str | None = Query(default=None, max_length=200),
    status: ReadingStatus | None = None,
) -> HTMLResponse:
    books, total = list_books_service(conn, q=q, status=status, limit=100)
    stats = get_stats_service(conn)
    return HTMLResponse(web.render_index(stats=stats, books=books, total=total, q=q, status=status))


@router.get("/health", response_model=HealthResponse)
def health(conn: DbConn) -> HealthResponse:
    conn.execute("SELECT 1").fetchone()
    return HealthResponse(status="ok", schema_version=schema_version(conn))


@router.get("/stats", response_model=Stats)
def stats(conn: DbConn) -> Stats:
    return get_stats_service(conn)


@books_router.get("", response_model=BookPage)
def list_books(
    conn: DbConn,
    q: str | None = Query(default=None, max_length=200),
    status: ReadingStatus | None = None,
    min_rating: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> BookPage:
    items, total = list_books_service(
        conn,
        q=q,
        status=status,
        min_rating=min_rating,
        limit=limit,
        offset=offset,
    )
    return BookPage(items=items, total=total, limit=limit, offset=offset)


@books_router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: int, conn: DbConn) -> BookOut:
    book = get_book_service(conn, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book
