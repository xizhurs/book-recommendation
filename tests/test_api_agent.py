from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from bookshelf import agent, llm
from bookshelf.config import Settings
from bookshelf.models import Recommendation, ToolCallRecord


def fake_result(answer: str = "Try Piranesi.") -> Recommendation:
    return Recommendation(
        answer=answer,
        provider="fake",
        model="fake-1",
        steps=[
            ToolCallRecord(
                name="search_library",
                arguments={"query": "dune"},
                result='{"total": 1}',
            )
        ],
    )


def test_recommend_endpoint_returns_the_answer(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_recommend(
        conn: sqlite3.Connection,
        *,
        query: str,
        settings: Settings,
        max_steps: int | None = None,
    ) -> Recommendation:
        captured.update(query=query, max_steps=max_steps)
        return fake_result()

    monkeypatch.setattr(agent, "recommend", fake_recommend)

    response = imported_client.post("/recommend", json={"query": "what next?", "max_steps": 2})

    assert response.status_code == 200
    assert response.json() == fake_result().model_dump(mode="json")
    assert captured == {"query": "what next?", "max_steps": 2}


def test_recommend_endpoint_reports_llm_failures(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_recommend(*args: object, **kwargs: object) -> Recommendation:
        raise llm.LLMError("connection refused")

    monkeypatch.setattr(agent, "recommend", failing_recommend)

    response = imported_client.post("/recommend", json={"query": "hello"})

    assert response.status_code == 502
    assert "connection refused" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 1001},
        {"query": "hello", "max_steps": 0},
        {"query": "hello", "max_steps": 9},
    ],
)
def test_recommend_endpoint_validates_payload(
    imported_client: TestClient,
    payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*args: object, **kwargs: object) -> Recommendation:
        raise AssertionError("the agent must not run for an invalid payload")

    monkeypatch.setattr(agent, "recommend", unexpected)

    assert imported_client.post("/recommend", json=payload).status_code == 422


def test_ask_page_renders_the_answer_and_steps(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "recommend", lambda *a, **k: fake_result())

    response = imported_client.get("/ask", params={"q": "what next?"})

    assert response.status_code == 200
    assert "Try Piranesi." in response.text
    assert "fake · fake-1 · 1 tool call" in response.text
    assert "search_library" in response.text
    assert "arguments and result" in response.text
    assert "LLM_PROVIDER=ollama" in response.text


def test_ask_page_escapes_model_output(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        agent,
        "recommend",
        lambda *a, **k: fake_result("<script>alert(1)</script>"),
    )

    response = imported_client.get("/ask", params={"q": "x"})

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_ask_page_reports_llm_errors(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_recommend(*args: object, **kwargs: object) -> Recommendation:
        raise llm.LLMError("ollama is not running")

    monkeypatch.setattr(agent, "recommend", failing_recommend)

    response = imported_client.get("/ask", params={"q": "hello"})

    assert response.status_code == 200
    assert "Could not reach the LLM: ollama is not running" in response.text


def test_ask_page_without_a_query_shows_the_form(imported_client: TestClient) -> None:
    response = imported_client.get("/ask")

    assert response.status_code == 200
    assert "What should I read next?" in response.text
    assert "The model chooses tools" in response.text
