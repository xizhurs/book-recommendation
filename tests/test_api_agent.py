from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bookshelf import agent, llm, repository
from bookshelf.config import Settings
from bookshelf.db import connect
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
        session_id: str | None = None,
    ) -> Recommendation:
        captured.update(query=query, max_steps=max_steps, session_id=session_id)
        return fake_result()

    monkeypatch.setattr(agent, "recommend", fake_recommend)

    response = imported_client.post(
        "/recommend", json={"query": "what next?", "max_steps": 2, "session_id": "chat-1"}
    )

    assert response.status_code == 200
    assert response.json() == fake_result().model_dump(mode="json")
    assert captured == {"query": "what next?", "max_steps": 2, "session_id": "chat-1"}


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


def test_recommend_endpoint_rejects_bad_session_ids(imported_client: TestClient) -> None:
    for bad in ("", "x" * 201, "caf\u00e9"):
        response = imported_client.post("/recommend", json={"query": "hi", "session_id": bad})
        assert response.status_code == 422


def _capture_agent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_recommend(conn: object, **kwargs: object) -> Recommendation:
        calls.append(kwargs)
        return fake_result()

    monkeypatch.setattr(agent, "recommend", fake_recommend)
    return calls


def test_ask_page_forwards_session_model_and_options(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _capture_agent(monkeypatch)

    response = imported_client.get(
        "/ask",
        params={
            "q": "next?",
            "session_id": "tab-1",
            "provider": "openai",
            "model": "my-model",
            "max_steps": "3",
            "no_rerank": "1",
        },
    )

    assert response.status_code == 200
    kwargs = calls[0]
    assert kwargs["session_id"] == "tab-1"
    assert kwargs["max_steps"] == 3
    chosen = kwargs["settings"]
    assert chosen.llm.llm_provider == "openai"  # type: ignore[attr-defined]
    assert chosen.llm.openai_model == "my-model"  # type: ignore[attr-defined]
    assert chosen.rerank_enabled is False  # type: ignore[attr-defined]
    assert 'value="tab-1"' in response.text
    assert 'value="my-model"' in response.text
    assert "checked" in response.text


def test_ask_page_treats_blank_form_fields_as_unset(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _capture_agent(monkeypatch)

    response = imported_client.get(
        "/ask",
        params={"q": "next?", "session_id": "", "provider": "", "model": "", "max_steps": ""},
    )

    assert response.status_code == 200
    assert calls[0]["session_id"] is None
    assert calls[0]["max_steps"] is None


def test_ask_page_rejects_bad_options_without_calling_the_model(
    imported_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _capture_agent(monkeypatch)

    for params in (
        {"q": "x", "session_id": "caf\u00e9"},
        {"q": "x", "provider": "bogus"},
        {"q": "x", "max_steps": "9"},
    ):
        response = imported_client.get("/ask", params=params)
        assert response.status_code == 200

    assert calls == []


def test_ask_page_shows_and_clears_session_history(
    imported_client: TestClient, db_path: Path
) -> None:
    seed = connect(db_path)
    repository.append_conversation_turn(seed, "tab-1", "after Austen?", "Try Emma.")
    seed.close()

    page = imported_client.get("/ask", params={"session_id": "tab-1"})
    assert "Earlier in this session (1)" in page.text
    assert "after Austen?" in page.text
    assert "Try Emma." in page.text

    cleared = imported_client.post(
        "/ask/clear", params={"session_id": "tab-1"}, follow_redirects=False
    )
    assert cleared.status_code == 303
    assert cleared.headers["location"] == "/ask?session_id=tab-1"
    assert (
        "Earlier in this session"
        not in imported_client.get("/ask", params={"session_id": "tab-1"}).text
    )
