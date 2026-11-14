# AGENTS.md

## Commands

- `uv sync` — install Python 3.12 (pinned in `.python-version`) and dependencies.
- `uv run python -m bookshelf.ingest.goodreads data/goodreads_library_export.csv` — import.
  Add `--include-reviews` only when review text is wanted; add `--db PATH` to override the DB.
- `uv run uvicorn bookshelf.main:app --reload --host 127.0.0.1 --port 8000` — run the API.
- `uv run pytest` — full suite.
- `uv run pytest tests/test_ingest_goodreads.py::test_import_report_counts` — single test.
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src` — checks.

## Layout and wiring

- `src/bookshelf/` is the only package. API routes (`api/routes.py`) call `services.py`, which
  calls `repository.py`, which owns SQL. Keep new endpoints on that path; do not put SQL in routes.
- `ingest/goodreads.py` is both the importer and its CLI. Re-imports are idempotent by Goodreads
  `Book Id`; duplicate CSV rows are skipped and existing reviews survive re-import without
  `--include-reviews`.
- `db.py` opens SQLite with foreign keys, WAL, and a busy timeout. `schema.sql` is applied
  idempotently by `db.init_db()` in the FastAPI lifespan. Schema version is `PRAGMA user_version`
  (currently 2); there is no migration framework yet, so new tables must be `CREATE ... IF NOT
  EXISTS` and additive.
- `openlibrary.py` is the only outbound HTTP code: a synchronous `httpx` client for
  `search.json`, plus parsing into `OpenLibraryWork`. It never touches SQLite. Responses are
  cached in `remote_cache` through `repository.py`, deduped by `matching.py`, and budgeted by
  `Settings.openlibrary_max_requests` in `services.discover`. Tests inject `httpx.MockTransport`
  or monkeypatch `openlibrary.fetch_search`; no test may hit the real network.
- Endpoints are synchronous `def` functions. `sqlite3` is synchronous; one connection per request.
  Do not introduce async SQLite or an ORM without a clear reason.
- `books` stores catalog metadata; `library_entries` stores personal status, rating, and dates.
  Keep them separate so future Open Library discoveries can exist without a personal entry.
- `tests/conftest.py` builds a temp SQLite DB and a `TestClient` that runs the app lifespan.

## Data and privacy

- `data/` contains the real Goodreads export and local DB and is gitignored. Never read, copy,
  log, or commit its contents. Use `tests/fixtures/goodreads_sample.csv` (fake data) in tests.
- `.env` is gitignored; only `.env.example` is committed. The API binds to `127.0.0.1`.
- Reviews are opt-in at import time; private notes are never imported. Do not add telemetry.
  The only outbound call is the Open Library search, and it sends search text only — never the
  library or review contents. Discovery responses are cached locally, not uploaded anywhere.
- Tests must use temporary databases and must not touch `data/`.

## Current scope

M2: Open Library search, SQLite caching (`remote_cache`), dedupe against the library, and a
per-search request budget. Do not add cross-encoder reranking, MCP, agent code, Docker, or
Langfuse until the matching milestone. Planned order: M3 cross-encoder reranking, M4 MCP + LLM
retrieval loop, M5 Docker/Langfuse/sandbox, M6 evaluations.
