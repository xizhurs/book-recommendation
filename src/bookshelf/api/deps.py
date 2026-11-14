from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from fastapi import Request

from ..config import Settings
from ..db import connect


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection per request; FastAPI closes it when the request ends."""
    conn = connect(Path(request.app.state.db_path))
    try:
        yield conn
    finally:
        conn.close()


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)
