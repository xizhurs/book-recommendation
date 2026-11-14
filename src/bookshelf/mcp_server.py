"""MCP server exposing the bookshelf tools over stdio.

Run with ``uv run python -m bookshelf.mcp_server`` and point an MCP client (Claude Desktop,
etc.) at that command. Each call opens its own SQLite connection; the schema init is idempotent.
"""

from __future__ import annotations

from contextlib import closing

from mcp.server.mcpserver import MCPServer

from . import tools
from .config import Settings
from .db import connect, init_db

mcp = MCPServer(
    "bookshelf",
    instructions=(
        "Local reading history and Open Library discovery. Use search_library and "
        "library_stats to ground answers in the reader's shelf, and discover_books for new "
        "suggestions. Review text is private and never returned."
    ),
)


def _run_tool(name: str, arguments: dict[str, object]) -> str:
    settings = Settings()
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        return tools.call_tool(conn, settings, name, arguments)


@mcp.tool()
def search_library(
    query: str | None = None,
    status: str | None = None,
    min_rating: int | None = None,
    limit: int = 10,
) -> str:
    """Search the reader's own library by title or author.

    Args:
        query: Title or author text.
        status: One of read, currently_reading, or to_read.
        min_rating: Only return books rated at least this many stars (1-5).
        limit: Maximum books to return (1-25).
    """
    arguments: dict[str, object] = {"limit": limit}
    if query is not None:
        arguments["query"] = query
    if status is not None:
        arguments["status"] = status
    if min_rating is not None:
        arguments["min_rating"] = min_rating
    return _run_tool("search_library", arguments)


@mcp.tool()
def library_stats() -> str:
    """Summarize the library: status counts, ratings, top authors, and top shelves."""
    return _run_tool("library_stats", {})


@mcp.tool()
def discover_books(query: str, limit: int = 8, include_owned: bool = False) -> str:
    """Search Open Library for books the reader does not own yet.

    Args:
        query: Topic, title, or author to search for.
        limit: Maximum candidates to return (1-15).
        include_owned: Also return books already in the library.
    """
    return _run_tool(
        "discover_books",
        {"query": query, "limit": limit, "include_owned": include_owned},
    )


@mcp.tool()
def get_book(book_id: int) -> str:
    """Fetch one library book by its numeric id."""
    return _run_tool("get_book", {"book_id": book_id})


if __name__ == "__main__":
    mcp.run()
