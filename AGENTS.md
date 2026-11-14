# AGENTS.md

## Commands

- `uv sync` — install Python 3.12 (pinned in `.python-version`) and dependencies.
- `uv run python -m bookshelf.ingest.goodreads data/goodreads_library_export.csv` — import.
  Add `--include-reviews` only when review text is wanted; add `--db PATH` to override the DB.
- `uv run python -m bookshelf.discover "query"` — discover via Open Library (cached, deduped,
  reranked). Flags: `--limit`, `--include-owned`, `--no-rerank`, `--json`, `--db PATH`.
- `uv run python -m bookshelf.ask "query"` — ask the agent (same loop as `/recommend`).
  Flags: `--max-steps`, `--model`, `--steps`, `--no-rerank`, `--json`, `--db PATH`.
- `uv run uvicorn bookshelf.main:app --reload --host 127.0.0.1 --port 8000` — run the API.
- `uv run python -m bookshelf.mcp_server` — run the MCP stdio server (same tools as the agent).
- `docker compose up --build` — run the API in a container on `127.0.0.1:8000` (mounts `./data`).
- `uv run pytest` — full suite.
- `uv run pytest tests/test_ingest_goodreads.py::test_import_report_counts` — single test.
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src` — checks.

## Layout and wiring

- `src/bookshelf/` is the only package. API routes (`api/routes.py`) call `services.py`, which
  calls `repository.py`, which owns SQL. Keep new endpoints on that path; do not put SQL in routes.
- `ingest/goodreads.py` is both the importer and its CLI. Re-imports are idempotent by Goodreads
  `Book Id`; duplicate CSV rows are skipped and existing reviews survive re-import without
  `--include-reviews`.
- `discover.py` is the discovery CLI. It must call `services.discover` rather than duplicating
  cache, dedupe, or rerank logic.
- `db.py` opens SQLite with foreign keys, WAL, and a busy timeout. `schema.sql` is applied
  idempotently by `db.init_db()` in the FastAPI lifespan. Schema version is `PRAGMA user_version`
  (currently 2); there is no migration framework yet, so new tables must be `CREATE ... IF NOT
  EXISTS` and additive.
- `openlibrary.py` is the only outbound HTTP code: a synchronous `httpx` client for
  `search.json`, plus parsing into `OpenLibraryWork`. It never touches SQLite. Responses are
  cached in `remote_cache` through `repository.py`, deduped by `matching.py`, and budgeted by
  `Settings.openlibrary_max_requests` in `services.discover`. Tests inject `httpx.MockTransport`
  or monkeypatch `openlibrary.fetch_search`; no test may hit the real network.
- `rerank.py` wraps a cross-encoder in a lazy, process-wide `Scorer`; `services.discover` accepts
  an injected scorer and reorders candidates before truncating to `limit`. Keep torch and
  sentence-transformers imports inside the lazy load so tests and non-rerank requests stay fast.
  Tests use a fake scorer; do not add tests that download model weights to the default run.
- `tools.py` owns the tool specs and handlers (`search_library`, `library_stats`,
  `discover_books`, `get_book`; `search_library` falls back to `matching.fuzzy_score` typo
  matching when `LIKE` finds nothing). Both `agent.py` and `mcp_server.py` call `tools.call_tool`; do
  not duplicate tool logic or SQL in either. Tool results are JSON and must never include review
  text — expose only `has_review`.
- `llm.py` is one OpenAI-compatible `httpx` client used for both `LLM_PROVIDER=openai` and
  `ollama` (Ollama serves `/v1/chat/completions`). Provider settings live in `LLMSettings` and
  intentionally use bare env names (`LLM_PROVIDER`, `OPENAI_*`, `OLLAMA_*`); `Settings.llm` nests
  them. Do not add provider-specific branches outside `llm.build_client`.
- `agent.recommend` runs the bounded tool loop: at most `llm_max_steps` model turns, then one
  final answer request. `POST /recommend`, `GET /ask`, and the `bookshelf.ask` CLI all call it.
  Tests inject a fake `ChatClient`; LLM HTTP behaviour is tested with `httpx.MockTransport`.
- Endpoints are synchronous `def` functions. `sqlite3` is synchronous; one connection per request.
  Do not introduce async SQLite or an ORM without a clear reason.
- `books` stores catalog metadata; `library_entries` stores personal status, rating, and dates.
  Keep them separate so future Open Library discoveries can exist without a personal entry.
- `tests/conftest.py` builds a temp SQLite DB and a `TestClient` that runs the app lifespan.

## Data and privacy

- `data/` contains the real Goodreads export and local DB and is gitignored. Never read, copy,
  log, or commit its contents. Use `tests/fixtures/goodreads_sample.csv` (fake data) in tests.
- `.env` is gitignored; only `.env.example` is committed. The API binds to `127.0.0.1`.
- Reviews are opt-in at import time; private notes are never imported. The only telemetry is
  opt-in Langfuse tracing (below); do not add any other. Outbound calls are: the Open Library search (search text only — never the library or review
  contents), the one-time cross-encoder download from Hugging Face (no personal data), and LLM
  chat requests. With `LLM_PROVIDER=ollama` LLM traffic stays on localhost. With
  `LLM_PROVIDER=openai` the question and compact tool results (titles, authors, status, ratings —
  never review text) go to OpenAI; document this and keep it opt-in. Discovery responses and
  models are cached locally, not uploaded anywhere.
- Langfuse tracing (`tracing.py`, M5) is opt-in: it is a no-op unless `LANGFUSE_PUBLIC_KEY` and
  `LANGFUSE_SECRET_KEY` are set, and `LANGFUSE_TRACING_ENABLED=false` forces it off. When on, it
  sends the full question, tool arguments, tool results, and model output for each agent run to
  `LANGFUSE_BASE_URL` (Langfuse Cloud by default), regardless of `LLM_PROVIDER`. Tool results
  never contain review text, so reviews never reach Langfuse. Keep the `langfuse` import inside
  `tracing._build_langfuse`; tracing errors must never fail a request. `tests/conftest.py` forces
  tracing off so a developer's real keys never send test traces.
- Tests must use temporary databases and must not touch `data/`. No test may call a real LLM,
  OpenAI, Ollama, or Open Library; use fake clients, `httpx.MockTransport`, and temp DBs.

## Current scope

M5 (done except the sandbox): Langfuse tracing of the agent loop, and Docker (`Dockerfile`,
`docker-compose.yml`; the image has not been built in CI or by the assistant). The sandbox for
dynamic analysis is deferred: nothing runs model-written code, so do not add a code-execution
tool without a design review. Keep evaluations for M6.

M4 (done): MCP tools and the LLM-driven retrieval loop, with local Ollama and hosted OpenAI
switchable through `LLM_PROVIDER` and one shared client.
