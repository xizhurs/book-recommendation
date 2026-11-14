from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bookshelf import openlibrary
from bookshelf.config import Settings
from bookshelf.main import create_app

SEARCH_DOCS = {
    "numFound": 3,
    "docs": [
        {
            "key": "/works/OL893415W",
            "title": "Dune",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 1965,
            "isbn": ["0441013597", "9780441013593"],
            "cover_i": 111,
            "edition_count": 100,
        },
        {
            "key": "/works/OL17863056W",
            "title": "Piranesi",
            "author_name": ["Susanna Clarke"],
            "first_publish_year": 2020,
            "isbn": ["9781635575637"],
            "cover_i": 222,
            "edition_count": 12,
        },
        {
            "key": "/works/OL27258W",
            "title": "Neuromancer",
            "author_name": ["William Gibson"],
            "first_publish_year": 1984,
            "isbn": ["9780441013594"],
            "cover_i": 333,
            "edition_count": 42,
        },
    ],
}


def install_fake_fetch(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, object]], body: str | None = None
) -> str:
    payload = body if body is not None else json.dumps(SEARCH_DOCS)

    def fake_fetch(
        query: str,
        *,
        limit: int,
        base_url: str = "",
        timeout: float = 0.0,
        transport: object = None,
    ) -> str:
        calls.append({"query": query, "limit": limit, "base_url": base_url, "timeout": timeout})
        return payload

    monkeypatch.setattr(openlibrary, "fetch_search", fake_fetch)
    return payload


def test_discover_returns_candidates_and_caches(
    client: TestClient, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []
    install_fake_fetch(monkeypatch, calls)

    first = client.get("/discover", params={"q": "science fiction"})
    second = client.get("/discover", params={"q": "science fiction"})

    assert first.status_code == 200
    assert first.json()["query"] == "science fiction"
    assert first.json()["total_found"] == 3
    assert first.json()["skipped_owned"] == 0
    assert first.json()["cached"] is False
    assert first.json()["requests_used"] == 1
    assert [item["title"] for item in first.json()["items"]] == [
        "Dune",
        "Piranesi",
        "Neuromancer",
    ]
    assert first.json()["items"][0] == {
        "openlibrary_key": "/works/OL893415W",
        "title": "Dune",
        "author": "Frank Herbert",
        "first_publish_year": 1965,
        "isbn13": "9780441013593",
        "cover_url": "https://covers.openlibrary.org/b/id/111-M.jpg",
        "edition_count": 100,
        "in_library": False,
    }

    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["requests_used"] == 0
    assert len(calls) == 1
    assert calls[0]["query"] == "science fiction"
    assert calls[0]["limit"] == 20  # limit * 2, floor 10

    cached_rows = conn.execute("SELECT COUNT(*) FROM remote_cache").fetchone()[0]
    assert cached_rows == 1


def test_discover_skips_books_already_in_library(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_fetch(monkeypatch, [])

    response = imported_client.get("/discover", params={"q": "dune"})

    assert response.status_code == 200
    body = response.json()
    assert body["total_found"] == 3
    assert body["skipped_owned"] == 2
    assert [item["title"] for item in body["items"]] == ["Neuromancer"]
    assert body["items"][0]["in_library"] is False


def test_discover_can_include_owned_books(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_fetch(monkeypatch, [])

    response = imported_client.get("/discover", params={"q": "dune", "include_owned": True})

    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["items"]] == ["Dune", "Piranesi", "Neuromancer"]
    assert [item["in_library"] for item in body["items"]] == [True, True, False]


def test_discover_respects_limit(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_fetch(monkeypatch, [])

    response = imported_client.get("/discover", params={"q": "dune", "limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["total_found"] == 3


def test_discover_revalidates_expired_cache(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    install_fake_fetch(monkeypatch, calls)
    app = create_app(
        Settings(
            db_path=db_path,
            openlibrary_cache_ttl_seconds=0,
            rerank_enabled=False,
        )
    )

    with TestClient(app) as client:
        first = client.get("/discover", params={"q": "dune"})
        second = client.get("/discover", params={"q": "dune"})

    assert first.json()["cached"] is False
    assert second.json()["cached"] is False
    assert second.json()["requests_used"] == 1
    assert len(calls) == 2


def test_discover_stops_when_budget_is_zero(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    install_fake_fetch(monkeypatch, calls)
    app = create_app(Settings(db_path=db_path, openlibrary_max_requests=0, rerank_enabled=False))

    with TestClient(app) as client:
        response = client.get("/discover", params={"q": "dune"})

    assert response.status_code == 200
    assert response.json() == {
        "query": "dune",
        "items": [],
        "total_found": 0,
        "skipped_owned": 0,
        "cached": False,
        "requests_used": 0,
        "reranked": False,
    }
    assert calls == []


def test_discover_reports_upstream_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_fetch(*args: object, **kwargs: object) -> str:
        raise openlibrary.OpenLibraryError("connection refused")

    monkeypatch.setattr(openlibrary, "fetch_search", failing_fetch)

    response = client.get("/discover", params={"q": "dune"})

    assert response.status_code == 502
    assert response.json()["detail"] == "Open Library request failed"


def test_discover_reports_unparseable_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_fetch(monkeypatch, [], body="not json")

    response = client.get("/discover", params={"q": "dune"})

    assert response.status_code == 502


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({}, 422),
        ({"q": ""}, 422),
        ({"q": "dune", "limit": 0}, 422),
        ({"q": "dune", "limit": 26}, 422),
        ({"q": "x" * 201}, 422),
    ],
)
def test_discover_validates_query(
    client: TestClient, params: dict[str, object], status: int
) -> None:
    assert client.get("/discover", params=params).status_code == status
