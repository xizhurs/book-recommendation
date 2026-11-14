from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from bookshelf import ask as cli
from bookshelf import llm
from bookshelf.config import Settings
from bookshelf.models import Recommendation, ToolCallRecord


def fake_result() -> Recommendation:
    return Recommendation(
        answer="Try Piranesi.",
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


def install_fake_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_recommend(
        conn: sqlite3.Connection,
        *,
        query: str,
        settings: Settings,
        max_steps: int | None = None,
    ) -> Recommendation:
        calls.append({"query": query, "settings": settings, "max_steps": max_steps, "conn": conn})
        return fake_result()

    monkeypatch.setattr(cli.agent, "recommend", fake_recommend)
    return calls


def test_prints_the_answer_and_summary(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_agent(monkeypatch)

    exit_code = cli.main(["--db", str(db_path), "what", "should", "I", "read?"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Try Piranesi." in captured.out
    assert "fake · fake-1 · 1 tool call" in captured.out
    assert "search_library" not in captured.out


def test_steps_flag_prints_tool_calls(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_agent(monkeypatch)

    exit_code = cli.main(["--db", str(db_path), "--steps", "what next?"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '[1] search_library {"query": "dune"}' in captured.out
    assert '{"total": 1}' in captured.out
    assert captured.out.index("search_library") < captured.out.index("Try Piranesi.")


def test_json_flag_prints_the_full_response(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install_fake_agent(monkeypatch)

    exit_code = cli.main(["--db", str(db_path), "--json", "what next?"])

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    assert body == fake_result().model_dump(mode="json")


def test_query_and_max_steps_are_forwarded(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_agent(monkeypatch)

    cli.main(["--db", str(db_path), "--max-steps", "2", "a", "book", "please"])

    assert len(calls) == 1
    assert calls[0]["query"] == "a book please"
    assert calls[0]["max_steps"] == 2


def test_no_rerank_disables_reranking(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_agent(monkeypatch)

    cli.main(["--db", str(db_path), "--no-rerank", "what next?"])

    settings = calls[0]["settings"]
    assert isinstance(settings, Settings)
    assert settings.rerank_enabled is False


def test_reranking_stays_enabled_by_default(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_agent(monkeypatch)

    cli.main(["--db", str(db_path), "what next?"])

    settings = calls[0]["settings"]
    assert isinstance(settings, Settings)
    assert settings.rerank_enabled is True


@pytest.mark.parametrize("value", ["0", "9", "-1"])
def test_rejects_out_of_range_max_steps(
    db_path: Path, value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main(["--db", str(db_path), "--max-steps", value, "hello"])

    assert exit_code == 2
    assert "--max-steps must be between 1 and 8" in capsys.readouterr().err


def test_rejects_blank_question(db_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["--db", str(db_path), "   "])

    assert exit_code == 2
    assert "Question cannot be empty" in capsys.readouterr().err


def test_reports_llm_failures(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_recommend(*args: object, **kwargs: object) -> Recommendation:
        raise llm.LLMError("ollama is not running")

    monkeypatch.setattr(cli.agent, "recommend", failing_recommend)

    exit_code = cli.main(["--db", str(db_path), "hello"])

    assert exit_code == 1
    assert "LLM request failed: ollama is not running" in capsys.readouterr().err
