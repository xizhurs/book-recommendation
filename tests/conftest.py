from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bookshelf.config import Settings
from bookshelf.db import connect, init_db
from bookshelf.ingest.goodreads import import_goodreads
from bookshelf.main import create_app

SAMPLE_CSV = Path(__file__).parent / "fixtures" / "goodreads_sample.csv"


@pytest.fixture
def sample_csv() -> Path:
    return SAMPLE_CSV


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "bookshelf.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_path)
    init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def app(db_path: Path) -> FastAPI:
    return create_app(Settings(db_path=db_path))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def imported_app(db_path: Path) -> FastAPI:
    connection = connect(db_path)
    try:
        init_db(connection)
        import_goodreads(connection, SAMPLE_CSV)
    finally:
        connection.close()
    return create_app(Settings(db_path=db_path))


@pytest.fixture
def imported_client(imported_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(imported_app) as test_client:
        yield test_client
