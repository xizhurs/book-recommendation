from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bookshelf.api import routes
from bookshelf.config import Settings
from bookshelf.main import create_app


@pytest.fixture
def stops(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr(routes, "_request_shutdown", lambda: calls.append(True))
    return calls


def test_pages_show_a_stop_button(client: TestClient) -> None:
    for path in ("/", "/find", "/ask"):
        assert 'action="/shutdown"' in client.get(path).text


def test_shutdown_returns_a_stopped_page_and_stops(client: TestClient, stops: list[bool]) -> None:
    response = client.post("/shutdown")

    assert response.status_code == 200
    assert "AI Bookshelf has stopped" in response.text
    assert stops == [True]


def test_same_origin_browser_requests_are_allowed(client: TestClient, stops: list[bool]) -> None:
    response = client.post(
        "/shutdown",
        headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"},
    )

    assert response.status_code == 200
    assert stops == [True]


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "https://evil.example"},
        {"sec-fetch-site": "cross-site"},
        {"sec-fetch-site": "same-site"},
    ],
)
def test_cross_origin_requests_are_refused(
    client: TestClient, stops: list[bool], headers: dict[str, str]
) -> None:
    response = client.post("/shutdown", headers=headers)

    assert response.status_code == 403
    assert stops == []


def test_get_does_not_stop_the_app(client: TestClient, stops: list[bool]) -> None:
    assert client.get("/shutdown").status_code == 405
    assert stops == []


def test_shutdown_can_be_disabled(db_path: Path, stops: list[bool]) -> None:
    app = create_app(Settings(db_path=db_path, rerank_enabled=False, allow_shutdown=False))
    with TestClient(app) as disabled:
        assert disabled.post("/shutdown").status_code == 404
    assert stops == []
