"""Thin, synchronous Open Library search client.

Network access is isolated here so tests can inject an ``httpx`` transport and the
rest of the app only deals with parsed dataclasses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

DEFAULT_USER_AGENT = "ai-bookshelf/0.1 (local personal library)"
SEARCH_FIELDS = "key,title,author_name,first_publish_year,isbn,cover_i,edition_count"


class OpenLibraryError(RuntimeError):
    """Open Library was unreachable or returned an unusable response."""


@dataclass(frozen=True, slots=True)
class OpenLibraryWork:
    key: str
    title: str
    author: str | None
    first_publish_year: int | None
    isbns: tuple[str, ...]
    cover_id: int | None
    edition_count: int


def fetch_search(
    query: str,
    *,
    limit: int,
    base_url: str = "https://openlibrary.org",
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Fetch a raw search.json payload. Raises ``OpenLibraryError`` on any HTTP failure."""
    params = {"q": query, "limit": str(limit), "fields": SEARCH_FIELDS}
    url = f"{base_url.rstrip('/')}/search.json"
    try:
        with httpx.Client(
            timeout=timeout,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            transport=transport,
            follow_redirects=True,
        ) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        raise OpenLibraryError(f"Open Library search failed: {exc}") from exc


def parse_search(payload: str) -> list[OpenLibraryWork]:
    """Parse search.json into works, skipping malformed documents."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise OpenLibraryError("Open Library returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise OpenLibraryError("Open Library returned an unexpected payload")
    docs = data.get("docs")
    if not isinstance(docs, list):
        raise OpenLibraryError("Open Library payload is missing its docs list")

    works: list[OpenLibraryWork] = []
    seen: set[str] = set()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        key = doc.get("key")
        title = doc.get("title")
        if not isinstance(key, str) or not isinstance(title, str) or key in seen:
            continue
        seen.add(key)
        works.append(
            OpenLibraryWork(
                key=key,
                title=title,
                author=_first_string(doc.get("author_name")),
                first_publish_year=_as_int(doc.get("first_publish_year")),
                isbns=tuple(value for value in _as_list(doc.get("isbn")) if isinstance(value, str)),
                cover_id=_as_int(doc.get("cover_i")),
                edition_count=_as_int(doc.get("edition_count")) or 0,
            )
        )
    return works


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _first_string(value: object) -> str | None:
    for item in _as_list(value):
        if isinstance(item, str):
            return item
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
