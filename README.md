# AI Bookshelf

Local-first reading history and, eventually, agentic book discovery.

**Current status: M1.** Import a Goodreads CSV export into SQLite and browse it through a
read-only FastAPI API. Discovery, cross-encoder reranking, MCP, and the agent come in later
milestones.

## Privacy first

- `data/` is gitignored. Keep the real Goodreads export and the SQLite database there.
- The API binds to `127.0.0.1` by default. Do not expose it publicly.
- Reviews are **not** imported unless you pass `--include-reviews`.
- `.env` is gitignored; only `.env.example` is committed.
- Tests use `tests/fixtures/goodreads_sample.csv`, which contains fake books. Never copy real
  reading data into fixtures.

## Setup

```bash
uv sync
cp .env.example .env
```

`uv` installs Python and the project into `.venv`.

## Import your library

```bash
uv run python -m bookshelf.ingest.goodreads data/goodreads_library_export.csv
```

Optional flags:

```bash
# Import review text too (off by default)
uv run python -m bookshelf.ingest.goodreads data/goodreads_library_export.csv --include-reviews

# Use a different database file
uv run python -m bookshelf.ingest.goodreads data/goodreads_library_export.csv --db data/other.db
```

Re-running the import is idempotent: books are upserted by Goodreads `Book Id`, duplicate rows
inside the CSV are skipped, and existing reviews are preserved when re-importing without
`--include-reviews`. The command prints counts and row-level errors, never book titles or reviews.

## Run the API

```bash
uv run uvicorn bookshelf.main:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs> for the interactive API docs.

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness plus SQLite schema version |
| `GET /books` | List/filter books. Params: `q`, `status`, `min_rating`, `limit`, `offset` |
| `GET /books/{id}` | One book and its reading entry |
| `GET /stats` | Counts by status, rating histogram, top authors/shelves |

`status` is one of `read`, `currently_reading`, or `to_read`.

## Tests and checks

```bash
uv run pytest
uv run pytest tests/test_ingest_goodreads.py::test_import_report_counts
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Tests create a temporary SQLite database and never touch `data/`.

## Architecture

```
src/bookshelf/
├── main.py            FastAPI app factory + lifespan DB init
├── config.py          pydantic-settings (BOOKSHELF_* env vars)
├── db.py              connections, pragmas, schema init
├── schema.sql         authors, books, library_entries, import_runs
├── models.py          Pydantic API models
├── repository.py      SQL queries
├── services.py        shared business logic (API today, MCP/agent later)
├── api/               thin FastAPI adapters
└── ingest/goodreads.py  CSV parser, upserts, CLI
```

- API routes call `services.py`; only `repository.py` and the importer contain SQL.
- FastAPI endpoints are synchronous. `sqlite3` is synchronous too; `def` endpoints run in the
  threadpool. One connection per request, with foreign keys, WAL, and a busy timeout enabled.
- `books` holds catalog metadata; `library_entries` holds personal status/rating/dates. Keeping
  them separate leaves room for Open Library discoveries that have no personal entry yet.
- Private notes are never imported. Review text is imported only with `--include-reviews`; when
  present it is returned by the local API, so keep the server bound to localhost.

## Roadmap

1. **M1 (done):** Goodreads import, SQLite, read-only FastAPI.
2. **M2:** Open Library search, metadata caching, dedupe, enrichment budget.
3. **M3:** Local cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L6-v2`).
4. **M4:** MCP tools and the LLM-driven retrieval loop.
5. **M5:** Docker, Langfuse tracing, sandbox only for dynamic analysis.
6. **M6:** Retrieval evaluations and local-vs-hosted model comparison.
