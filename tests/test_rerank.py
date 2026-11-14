from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bookshelf import openlibrary, rerank
from bookshelf.config import Settings
from bookshelf.main import create_app

DOCS = {
    "docs": [
        {
            "key": "/works/OL1W",
            "title": "A Book About Gardens",
            "author_name": ["Ada Green"],
            "first_publish_year": 1999,
            "isbn": ["9780000000001"],
        },
        {
            "key": "/works/OL2W",
            "title": "Dune",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 1965,
            "isbn": ["9780441013593"],
        },
        {
            "key": "/works/OL3W",
            "title": "Children of Dune",
            "author_name": ["Frank Herbert"],
            "first_publish_year": 1976,
            "isbn": ["9780593098240"],
        },
    ]
}


class FakeScorer:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls.append((query, list(documents)))
        return self._scores


def make_client(db_path: Path, **overrides: object) -> TestClient:
    defaults: dict[str, object] = {"rerank_enabled": True}
    settings = Settings(db_path=db_path, **{**defaults, **overrides})
    return TestClient(create_app(settings))


def install_fake_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(DOCS)

    def fake_fetch(
        query: str,
        *,
        limit: int,
        base_url: str = "",
        timeout: float = 0.0,
        transport: object = None,
    ) -> str:
        return payload

    monkeypatch.setattr(openlibrary, "fetch_search", fake_fetch)


def test_describe_builds_document_text() -> None:
    assert rerank.describe("Dune", "Frank Herbert", 1965) == "Dune — Frank Herbert (1965)"
    assert rerank.describe("Dune", "Frank Herbert", None) == "Dune — Frank Herbert"
    assert rerank.describe("Dune", None, None) == "Dune"


def test_order_is_descending_and_stable() -> None:
    assert rerank.order([0.1, 0.9, 0.9, -1.0]) == [1, 2, 0, 3]
    assert rerank.order([]) == []


def test_scorer_does_not_load_a_model_for_empty_input() -> None:
    scorer = rerank.CrossEncoderScorer("cross-encoder/ms-marco-MiniLM-L6-v2")

    assert scorer.score("dune", []) == []
    assert scorer.loaded is False


def test_get_scorer_reuses_one_instance() -> None:
    rerank.get_scorer.cache_clear()
    try:
        assert rerank.get_scorer("model-a") is rerank.get_scorer("model-a")
        assert rerank.get_scorer("model-a") is not rerank.get_scorer("model-b")
    finally:
        rerank.get_scorer.cache_clear()


def test_discover_reranks_before_truncating(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_fetch(monkeypatch)
    scorer = FakeScorer([0.2, 0.1, 0.9])
    monkeypatch.setattr(rerank, "get_scorer", lambda name: scorer)

    with make_client(db_path) as client:
        response = client.get("/discover", params={"q": "dune", "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["reranked"] is True
    assert [item["title"] for item in body["items"]] == ["Children of Dune", "A Book About Gardens"]
    assert len(scorer.calls) == 1
    query, documents = scorer.calls[0]
    assert query == "dune"
    assert documents == [
        "A Book About Gardens — Ada Green (1999)",
        "Dune — Frank Herbert (1965)",
        "Children of Dune — Frank Herbert (1976)",
    ]


def test_discover_only_scores_rerank_candidates(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_fetch(monkeypatch)
    scorer = FakeScorer([0.1, 0.9])
    monkeypatch.setattr(rerank, "get_scorer", lambda name: scorer)

    with make_client(db_path, rerank_candidates=2) as client:
        response = client.get("/discover", params={"q": "dune", "limit": 10})

    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == [
        "Dune",
        "A Book About Gardens",
        "Children of Dune",
    ]
    assert len(scorer.calls[0][1]) == 2


def test_discover_can_opt_out_of_reranking(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_fetch(monkeypatch)

    def unexpected_scorer(name: str) -> rerank.Scorer:
        raise AssertionError("reranker should not be loaded")

    monkeypatch.setattr(rerank, "get_scorer", unexpected_scorer)

    with make_client(db_path) as client:
        response = client.get("/discover", params={"q": "dune", "rerank": "false"})

    assert response.status_code == 200
    assert response.json()["reranked"] is False
    assert [item["title"] for item in response.json()["items"]] == [
        "A Book About Gardens",
        "Dune",
        "Children of Dune",
    ]


def test_reranking_is_disabled_by_settings(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_fetch(monkeypatch)

    def unexpected_scorer(name: str) -> rerank.Scorer:
        raise AssertionError("reranker should not be loaded")

    monkeypatch.setattr(rerank, "get_scorer", unexpected_scorer)

    with make_client(db_path, rerank_enabled=False) as client:
        response = client.get("/discover", params={"q": "dune"})

    assert response.status_code == 200
    assert response.json()["reranked"] is False


def test_find_page_reports_reranked_results(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_fetch(monkeypatch)
    scorer = FakeScorer([0.9, 0.1, 0.5])
    monkeypatch.setattr(rerank, "get_scorer", lambda name: scorer)

    with make_client(db_path) as client:
        response = client.get("/find", params={"q": "dune"})

    assert response.status_code == 200
    assert "reranked" in response.text
    assert response.text.index("A Book About Gardens") < response.text.index("Children of Dune")


def test_scorer_passes_the_hf_token_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    captured: dict[str, object] = {}

    class FakeCrossEncoder:
        def __init__(self, name: str, **kwargs: object) -> None:
            captured.update(kwargs)

        def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
            return [0.5 for _ in pairs]

    fake_module = types.SimpleNamespace(CrossEncoder=FakeCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")

    assert rerank.CrossEncoderScorer("m").score("q", ["d"]) == [0.5]
    assert captured == {"device": "cpu", "token": "hf_test_token"}

    monkeypatch.delenv("HF_TOKEN")
    monkeypatch.chdir("/")  # no .env to pick up
    captured.clear()
    rerank.CrossEncoderScorer("m").score("q", ["d"])
    assert captured["token"] is None
