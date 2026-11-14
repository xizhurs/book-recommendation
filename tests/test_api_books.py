from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "schema_version": 1}


def test_list_books(imported_client: TestClient) -> None:
    response = imported_client.get("/books")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["title"] for item in body["items"]] == [
        "Dune",
        "Piranesi",
        "The Dispossessed",
        "The Left Hand of Darkness",
        "This Is How You Lose the Time War",
    ]


def test_filter_by_status(imported_client: TestClient) -> None:
    read = imported_client.get("/books", params={"status": "read"})
    current = imported_client.get("/books", params={"status": "currently_reading"})
    to_read = imported_client.get("/books", params={"status": "to_read"})

    assert read.json()["total"] == 3
    assert current.json()["total"] == 1
    assert to_read.json()["total"] == 1


def test_search_by_title_or_author(imported_client: TestClient) -> None:
    response = imported_client.get("/books", params={"q": "le guin"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["author"] for item in body["items"]} == {"Ursula K. Le Guin"}


def test_search_escapes_like_wildcards(imported_client: TestClient) -> None:
    response = imported_client.get("/books", params={"q": "%"})

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_filter_by_min_rating(imported_client: TestClient) -> None:
    response = imported_client.get("/books", params={"min_rating": 4})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["rating"] for item in body["items"]} == {4, 5}


def test_pagination(imported_client: TestClient) -> None:
    first = imported_client.get("/books", params={"limit": 2, "offset": 0})
    last = imported_client.get("/books", params={"limit": 2, "offset": 4})

    assert first.json()["total"] == 5
    assert len(first.json()["items"]) == 2
    assert len(last.json()["items"]) == 1


def test_get_book(imported_client: TestClient) -> None:
    response = imported_client.get("/books/1")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "The Left Hand of Darkness"
    assert body["author"] == "Ursula K. Le Guin"
    assert body["status"] == "read"
    assert body["date_read"] == "2024-01-15"
    assert body["review"] is None


def test_missing_book_returns_404(imported_client: TestClient) -> None:
    response = imported_client.get("/books/9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Book not found"


def test_stats(imported_client: TestClient) -> None:
    response = imported_client.get("/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["total_books"] == 5
    assert body["by_status"] == {"read": 3, "currently_reading": 1, "to_read": 1}
    assert body["rating_counts"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1, "unrated": 3}
    assert body["average_rating"] == 4.5
    assert body["top_authors"][0] == {"name": "Ursula K. Le Guin", "count": 2}
    assert body["top_shelves"][0] == {"name": "science-fiction", "count": 4}


def test_invalid_status_is_rejected(imported_client: TestClient) -> None:
    response = imported_client.get("/books", params={"status": "bogus"})

    assert response.status_code == 422


def test_limit_is_bounded(imported_client: TestClient) -> None:
    response = imported_client.get("/books", params={"limit": 101})

    assert response.status_code == 422
