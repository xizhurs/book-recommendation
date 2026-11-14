from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from bookshelf import discover as cli
from bookshelf import openlibrary, rerank

DOCS = {
    "docs": [
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


def test_cli_prints_results(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_fetch(monkeypatch)

    exit_code = cli.main(["--db", str(db_path), "--no-rerank", "dune", "frank", "herbert"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "1. Dune by Frank Herbert (1965)" in captured.out
    assert "2. Children of Dune by Frank Herbert (1976)" in captured.out
    assert "2 of 2 results · fresh" in captured.out


def test_cli_prints_json(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_fetch(monkeypatch)

    exit_code = cli.main(["--db", str(db_path), "--no-rerank", "--json", "dune"])

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["query"] == "dune"
    assert body["reranked"] is False
    assert [item["title"] for item in body["items"]] == ["Dune", "Children of Dune"]


def test_cli_reranks_by_default(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_fetch(monkeypatch)
    monkeypatch.setenv("BOOKSHELF_RERANK_ENABLED", "true")
    scorer = FakeScorer([0.1, 0.9])
    monkeypatch.setattr(rerank, "get_scorer", lambda name: scorer)

    exit_code = cli.main(["--db", str(db_path), "dune"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.index("Children of Dune") < captured.out.index("Dune by Frank Herbert")
    assert "reranked" in captured.out
    assert scorer.calls == [
        ("dune", ["Dune — Frank Herbert (1965)", "Children of Dune — Frank Herbert (1976)"])
    ]


def test_cli_no_rerank_skips_the_model(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_fetch(monkeypatch)

    def unexpected_scorer(name: str) -> rerank.Scorer:
        raise AssertionError("model should not be loaded")

    monkeypatch.setattr(rerank, "get_scorer", unexpected_scorer)

    assert cli.main(["--db", str(db_path), "--no-rerank", "dune"]) == 0


def test_cli_reports_openlibrary_failure(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_fetch(*args: object, **kwargs: object) -> str:
        raise openlibrary.OpenLibraryError("connection refused")

    monkeypatch.setattr(openlibrary, "fetch_search", failing_fetch)

    exit_code = cli.main(["--db", str(db_path), "dune"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Open Library request failed" in captured.err


@pytest.mark.parametrize("limit", ["0", "26"])
def test_cli_rejects_out_of_range_limit(db_path: Path, limit: str) -> None:
    assert cli.main(["--db", str(db_path), "--limit", limit, "dune"]) == 2
