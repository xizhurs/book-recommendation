from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from bookshelf import mcp_server
from bookshelf.db import connect, init_db
from bookshelf.ingest.goodreads import import_goodreads


def record_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, object]]]:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_run_tool(name: str, arguments: dict[str, object]) -> str:
        calls.append((name, arguments))
        return '{"ok": true}'

    monkeypatch.setattr(mcp_server, "_run_tool", fake_run_tool)
    return calls


def test_server_registers_the_four_tools() -> None:
    names = [tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())]

    assert names == ["search_library", "library_stats", "discover_books", "get_book"]


def test_search_library_forwards_every_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = record_calls(monkeypatch)

    assert mcp_server.search_library("dune", status="read", min_rating=4, limit=5) == '{"ok": true}'
    assert calls == [
        (
            "search_library",
            {"limit": 5, "query": "dune", "status": "read", "min_rating": 4},
        )
    ]


def test_search_library_only_sends_provided_optionals(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = record_calls(monkeypatch)

    mcp_server.search_library()

    assert calls == [("search_library", {"limit": 10})]


def test_library_stats_passes_no_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = record_calls(monkeypatch)

    mcp_server.library_stats()

    assert calls == [("library_stats", {})]


def test_discover_books_has_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = record_calls(monkeypatch)

    mcp_server.discover_books("cozy fantasy")

    assert calls == [
        ("discover_books", {"query": "cozy fantasy", "limit": 8, "include_owned": False})
    ]


def test_get_book_forwards_the_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = record_calls(monkeypatch)

    mcp_server.get_book(7)

    assert calls == [("get_book", {"book_id": 7})]


def test_search_library_reads_the_configured_database(
    db_path: Path, sample_csv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = connect(db_path)
    try:
        init_db(connection)
        import_goodreads(connection, sample_csv)
    finally:
        connection.close()
    monkeypatch.setenv("BOOKSHELF_DB_PATH", str(db_path))

    payload = json.loads(mcp_server.search_library(query="dune"))

    assert payload["total"] == 1
    books: list[dict[str, Any]] = payload["books"]
    assert books[0]["title"] == "Dune"
    assert "review" not in books[0]


def test_server_instructions_share_the_agents_discovery_guidance() -> None:
    from bookshelf import agent, tools

    instructions = mcp_server.mcp.instructions or ""
    assert tools.TASTE_GUIDANCE in instructions
    assert tools.DISCOVERY_GUIDANCE in instructions
    assert tools.TASTE_GUIDANCE in agent.SYSTEM_PROMPT
    assert tools.DISCOVERY_GUIDANCE in agent.SYSTEM_PROMPT
    assert "Review text is private" in instructions
