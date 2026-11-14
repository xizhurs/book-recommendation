from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from . import openlibrary, repository
from .config import Settings
from .matching import normalize_name, title_author_key
from .models import BookOut, DiscoveryItem, DiscoveryPage, ReadingStatus, Stats

CACHE_SOURCE = "openlibrary.search"
MAX_FETCH_LIMIT = 40


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


def discover(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int,
    include_owned: bool,
    settings: Settings,
) -> DiscoveryPage:
    """Search Open Library for books the library does not already contain.

    Responses are cached in SQLite for ``openlibrary_cache_ttl_seconds`` and every call is
    bounded by ``openlibrary_max_requests`` so a repeated search never becomes a request storm.
    """
    query = query.strip()
    fetch_limit = min(max(limit * 2, 10), MAX_FETCH_LIMIT)
    cache_key = f"{normalize_name(query)}|{fetch_limit}"

    now = datetime.now(UTC)
    payload = repository.get_cached_payload(
        conn,
        source=CACHE_SOURCE,
        cache_key=cache_key,
        now=now.isoformat(),
    )
    cached = payload is not None
    requests_used = 0

    if payload is None:
        if settings.openlibrary_max_requests < 1:
            return DiscoveryPage(
                query=query,
                items=[],
                total_found=0,
                skipped_owned=0,
                cached=False,
                requests_used=0,
            )
        payload = openlibrary.fetch_search(
            query,
            limit=fetch_limit,
            base_url=settings.openlibrary_base_url,
            timeout=settings.openlibrary_timeout_seconds,
        )
        requests_used = 1
        expires_at = now + timedelta(seconds=settings.openlibrary_cache_ttl_seconds)
        repository.store_cached_payload(
            conn,
            source=CACHE_SOURCE,
            cache_key=cache_key,
            payload=payload,
            fetched_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )

    works = openlibrary.parse_search(payload)
    library_isbns, library_titles = repository.library_identity(conn)

    items: list[DiscoveryItem] = []
    skipped_owned = 0
    for work in works:
        owned = any(isbn in library_isbns for isbn in work.isbns) or (
            title_author_key(work.title, work.author) in library_titles
        )
        if owned:
            skipped_owned += 1
            if not include_owned:
                continue
        if len(items) >= limit:
            continue
        items.append(_to_item(work, owned))

    return DiscoveryPage(
        query=query,
        items=items,
        total_found=len(works),
        skipped_owned=skipped_owned,
        cached=cached,
        requests_used=requests_used,
    )


def _to_item(work: openlibrary.OpenLibraryWork, owned: bool) -> DiscoveryItem:
    isbn13 = next((isbn for isbn in work.isbns if len(isbn) == 13), None)
    cover_url = (
        f"https://covers.openlibrary.org/b/id/{work.cover_id}-M.jpg"
        if work.cover_id is not None
        else None
    )
    return DiscoveryItem(
        openlibrary_key=work.key,
        title=work.title,
        author=work.author,
        first_publish_year=work.first_publish_year,
        isbn13=isbn13,
        cover_url=cover_url,
        edition_count=work.edition_count,
        in_library=owned,
    )
