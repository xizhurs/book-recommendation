from __future__ import annotations

import json

import httpx
import pytest

from bookshelf import openlibrary

SEARCH_BODY = {
    "numFound": 2,
    "docs": [
        {
            "key": "/works/OL1W",
            "title": "Piranesi",
            "author_name": ["Susanna Clarke"],
            "first_publish_year": 2020,
            "isbn": ["9781635575637", "1635575632"],
            "cover_i": 987654,
            "edition_count": 12,
        },
        {
            "key": "/works/OL2W",
            "title": "Broken",
            "author_name": "not-a-list",
            "first_publish_year": "unknown",
            "isbn": ["short"],
        },
    ],
}


def test_parse_search_extracts_works() -> None:
    works = openlibrary.parse_search(json.dumps(SEARCH_BODY))

    assert [work.key for work in works] == ["/works/OL1W", "/works/OL2W"]
    first, second = works
    assert first.title == "Piranesi"
    assert first.author == "Susanna Clarke"
    assert first.first_publish_year == 2020
    assert first.isbns == ("9781635575637", "1635575632")
    assert first.cover_id == 987654
    assert first.edition_count == 12

    assert second.author is None
    assert second.first_publish_year is None
    assert second.cover_id is None
    assert second.edition_count == 0


def test_parse_search_skips_documents_without_key_or_title() -> None:
    payload = json.dumps(
        {
            "docs": [
                {"title": "No key"},
                {"key": "/works/OL3W"},
                {"key": "/works/OL4W", "title": "Kept"},
                {"key": "/works/OL4W", "title": "Duplicate key"},
                "not-a-document",
            ]
        }
    )

    works = openlibrary.parse_search(payload)

    assert [work.title for work in works] == ["Kept"]


@pytest.mark.parametrize(
    "payload",
    ["not json", "[]", '{"docs": "nope"}'],
)
def test_parse_search_rejects_unusable_payloads(payload: str) -> None:
    with pytest.raises(openlibrary.OpenLibraryError):
        openlibrary.parse_search(payload)


def test_fetch_search_sends_bounded_request() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = request.url.params["q"]
        captured["limit"] = request.url.params["limit"]
        captured["fields"] = request.url.params["fields"]
        captured["user_agent"] = request.headers["user-agent"]
        return httpx.Response(200, json=SEARCH_BODY)

    payload = openlibrary.fetch_search(
        "piranesi",
        limit=7,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    assert captured == {
        "path": "/search.json",
        "query": "piranesi",
        "limit": "7",
        "fields": openlibrary.SEARCH_FIELDS,
        "user_agent": openlibrary.DEFAULT_USER_AGENT,
    }
    assert json.loads(payload) == SEARCH_BODY


def test_fetch_search_wraps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with pytest.raises(openlibrary.OpenLibraryError):
        openlibrary.fetch_search("dune", limit=5, transport=httpx.MockTransport(handler))


def test_fetch_search_wraps_connection_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(openlibrary.OpenLibraryError):
        openlibrary.fetch_search("dune", limit=5, transport=httpx.MockTransport(handler))
