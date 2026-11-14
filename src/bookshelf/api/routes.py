from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from .. import agent, llm, openlibrary, rerank, web
from ..config import Settings
from ..db import schema_version
from ..models import (
    BookOut,
    BookPage,
    DiscoveryPage,
    HealthResponse,
    ReadingStatus,
    Recommendation,
    RecommendRequest,
    Stats,
)
from ..services import discover as discover_service
from ..services import get_book as get_book_service
from ..services import get_stats as get_stats_service
from ..services import list_books as list_books_service
from .deps import get_db, get_settings

DbConn = Annotated[sqlite3.Connection, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

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


@router.get("/find", response_class=HTMLResponse, include_in_schema=False)
def find_books(
    conn: DbConn,
    settings: AppSettings,
    q: str | None = Query(default=None, max_length=200),
) -> HTMLResponse:
    page: DiscoveryPage | None = None
    error: str | None = None
    if q and q.strip():
        scorer = rerank.get_scorer(settings.rerank_model) if settings.rerank_enabled else None
        try:
            page = discover_service(
                conn,
                query=q,
                limit=12,
                include_owned=False,
                settings=settings,
                scorer=scorer,
            )
        except openlibrary.OpenLibraryError:
            error = "Open Library could not be reached. Try again in a moment."
    return HTMLResponse(web.render_discover(query=q, page=page, error=error))


@router.get("/discover", response_model=DiscoveryPage)
def discover(
    conn: DbConn,
    settings: AppSettings,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=25),
    include_owned: bool = False,
    use_rerank: bool | None = Query(default=None, alias="rerank"),
) -> DiscoveryPage:
    rerank_enabled = settings.rerank_enabled if use_rerank is None else use_rerank
    scorer = rerank.get_scorer(settings.rerank_model) if rerank_enabled else None
    try:
        return discover_service(
            conn,
            query=q,
            limit=limit,
            include_owned=include_owned,
            settings=settings,
            scorer=scorer,
        )
    except openlibrary.OpenLibraryError as exc:
        raise HTTPException(status_code=502, detail="Open Library request failed") from exc


@router.get("/ask", response_class=HTMLResponse, include_in_schema=False)
def ask_page(
    conn: DbConn,
    settings: AppSettings,
    q: str | None = Query(default=None, max_length=1000),
    session_id: str | None = Query(
        default=None, min_length=1, max_length=200, pattern=r"^[\x20-\x7e]+$"
    ),
) -> HTMLResponse:
    result: Recommendation | None = None
    error: str | None = None
    if q and q.strip():
        try:
            result = agent.recommend(conn, query=q, settings=settings, session_id=session_id)
        except llm.LLMError as exc:
            error = f"Could not reach the LLM: {exc}"
    return HTMLResponse(web.render_ask(query=q, result=result, error=error))


@router.post("/recommend", response_model=Recommendation)
def recommend(
    conn: DbConn,
    settings: AppSettings,
    payload: RecommendRequest,
) -> Recommendation:
    try:
        return agent.recommend(
            conn,
            query=payload.query,
            settings=settings,
            max_steps=payload.max_steps,
            session_id=payload.session_id,
        )
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc


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
