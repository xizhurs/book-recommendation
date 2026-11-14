# AI Bookshelf

Local-first reading history and, eventually, agentic book discovery.

**Current status: M3.** Import a Goodreads CSV into SQLite, browse it through a read-only
FastAPI API or the local web pages, search Open Library for books you do not own yet, and
rerank those results with a local cross-encoder. MCP and the agent come in later milestones.

## Privacy first

- `data/` is gitignored. Keep the real Goodreads export and the SQLite database there.
- The API binds to `127.0.0.1` by default. Do not expose it publicly.
- Reviews are **not** imported unless you pass `--include-reviews`.
- `.env` is gitignored; only `.env.example` is committed.
- Open Library searches send only the search text. Your library and reviews never leave the
  machine; responses are cached locally in SQLite.
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

Open <http://127.0.0.1:8000/> for the bookshelf UI, <http://127.0.0.1:8000/find> to search
Open Library, or <http://127.0.0.1:8000/docs> for the interactive API docs.

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness plus SQLite schema version |
| `GET /books` | List/filter books. Params: `q`, `status`, `min_rating`, `limit`, `offset` |
| `GET /books/{id}` | One book and its reading entry |
| `GET /stats` | Counts by status, rating histogram, top authors/shelves |
| `GET /discover` | Open Library search. Params: `q` (required), `limit`, `include_owned`, `rerank` |

`status` is one of `read`, `currently_reading`, or `to_read`.

## Discover books

`GET /discover?q=...` queries Open Library's search API and drops anything already in your
library, matching by ISBN first and then by normalized title + author.

- Results are cached in the `remote_cache` table for `BOOKSHELF_OPENLIBRARY_CACHE_TTL_SECONDS`
  (default one day), so repeated searches make no network calls. Responses report `cached` and
  `requests_used`.
- Each call may make at most `BOOKSHELF_OPENLIBRARY_MAX_REQUESTS` outbound requests (default 3).
  Set it to `0` for a strictly offline mode: the endpoint then only reads the cache.
- Override the host with `BOOKSHELF_OPENLIBRARY_BASE_URL` and the timeout with
  `BOOKSHELF_OPENLIBRARY_TIMEOUT_SECONDS`.
- Only the search text is sent to Open Library. `include_owned=true` also returns books you
  already have, flagged with `in_library`.

## Reranking

Discovery results are reranked locally with
[`cross-encoder/ms-marco-MiniLM-L6-v2`](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2),
scoring each candidate's `Title — Author (year)` against the query and keeping the best `limit`.

- First rerank downloads the model (~90 MB) from Hugging Face into the local HF cache and loads
  it on CPU; later requests reuse the in-process instance. This is the only other outbound
  request besides the Open Library search, and it sends no library data.
- `GET /discover` reranks by default. Pass `rerank=false` to keep Open Library's order, or set
  `BOOKSHELF_RERANK_ENABLED=false` to disable the model entirely (no torch usage, no download).
- `BOOKSHELF_RERANK_CANDIDATES` caps how many results are scored (`25` by default).
  `BOOKSHELF_RERANK_MODEL` selects a different cross-encoder.
- Responses include `"reranked": true/false`; the `/find` page shows it in the result summary.

## Tests and checks

```bash
uv run pytest
uv run pytest tests/test_ingest_goodreads.py::test_import_report_counts
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Tests create a temporary SQLite database and never touch `data/`. Open Library is always mocked
via `httpx.MockTransport` or a patched `fetch_search`, and reranking is tested with a fake
`Scorer`, so the suite needs no network and never downloads model weights.

## Architecture

```
src/bookshelf/
├── main.py            FastAPI app factory + lifespan DB init
├── config.py          pydantic-settings (BOOKSHELF_* env vars)
├── db.py              connections, pragmas, schema init
├── schema.sql         authors, books, library_entries, import_runs, remote_cache
├── models.py          Pydantic API models
├── repository.py      SQL queries
├── services.py        shared business logic (API today, MCP/agent later)
├── openlibrary.py     Open Library HTTP client + parsing
├── matching.py        title/author normalization for dedupe
├── rerank.py          lazy local cross-encoder scoring
├── web.py             server-rendered HTML pages
├── api/               thin FastAPI adapters
└── ingest/goodreads.py  CSV parser, upserts, CLI
```

- API routes call `services.py`; only `repository.py` and the importer contain SQL.
- `openlibrary.py` is the only module that makes outbound HTTP calls. `rerank.py` only downloads
  a model from Hugging Face on first use; inference stays local.
- FastAPI endpoints are synchronous. `sqlite3` is synchronous too; `def` endpoints run in the
  threadpool. One connection per request, with foreign keys, WAL, and a busy timeout enabled.
- `books` holds catalog metadata; `library_entries` holds personal status/rating/dates. Keeping
  them separate leaves room for Open Library discoveries that have no personal entry yet.
- Private notes are never imported. Review text is imported only with `--include-reviews`; when
  present it is returned by the local API, so keep the server bound to localhost.

## Roadmap

1. **M1 (done):** Goodreads import, SQLite, read-only FastAPI.
2. **M2 (done):** Open Library search, metadata caching, dedupe, enrichment budget.
3. **M3 (done):** Local cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L6-v2`).
4. **M4:** MCP tools and the LLM-driven retrieval loop.
5. **M5:** Docker, Langfuse tracing, sandbox only for dynamic analysis.
6. **M6:** Retrieval evaluations and local-vs-hosted model comparison.
