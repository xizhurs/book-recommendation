from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request

from ..db import connect


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection per request; FastAPI closes it when the request ends."""
    conn = connect(Path(request.app.state.db_path))
    try:
        yield conn
    finally:
        conn.close()
