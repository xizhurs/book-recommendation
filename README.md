# AI Bookshelf

[![CI](https://github.com/xizhurs/book-recommendation/actions/workflows/ci.yml/badge.svg)](https://github.com/xizhurs/book-recommendation/actions/workflows/ci.yml)

Local-first reading history with agentic book discovery.

**Current status: M5** (Docker and optional Langfuse tracing; sandbox deferred). Import a Goodreads CSV into SQLite, browse it through a read-only
FastAPI API or the local web pages, search Open Library for books you do not own yet, rerank
those results with a local cross-encoder, and ask an LLM for recommendations through a
tool-calling loop. Both a local Ollama model and the hosted OpenAI API are supported.

## Privacy first

- `data/` is gitignored. Keep the real Goodreads export and the SQLite database there.
- The API binds to `127.0.0.1` by default. Do not expose it publicly.
- Reviews are **not** imported unless you pass `--include-reviews`.
- `.env` is gitignored; only `.env.example` is committed.
- Open Library searches send only the search text. Your library and reviews never leave the
  machine; responses are cached locally in SQLite.
- **LLM tool results never contain review text** — only a `has_review` flag. With
  `LLM_PROVIDER=ollama`, your questions and library metadata stay on this machine. With
  `LLM_PROVIDER=openai`, the question and the compact tool results (titles, authors, status,
  ratings) are sent to OpenAI; nothing else is.
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
Open Library, <http://127.0.0.1:8000/ask> to ask for recommendations, or
<http://127.0.0.1:8000/docs> for the interactive API docs.

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness plus SQLite schema version |
| `GET /books` | List/filter books. Params: `q`, `status`, `min_rating`, `limit`, `offset` |
| `GET /books/{id}` | One book and its reading entry |
| `GET /stats` | Counts by status, rating histogram, top authors/shelves |
| `GET /discover` | Open Library search. Params: `q` (required), `limit`, `include_owned`, `rerank` |
| `POST /recommend` | LLM recommendation. JSON: `{"query": "...", "max_steps": 4}` |
| `GET /ask` | HTML page running the same loop as `/recommend`, server-rendered |
| `POST /ask/clear?session_id=` | Delete a session's conversation memory (used by the `/ask` page) |
| `POST /shutdown` | Stops the server (the **Stop app** button in the page header); refuses cross-origin browser requests; disable with `BOOKSHELF_ALLOW_SHUTDOWN=false` |

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

## Discover from the CLI

The same pipeline (cache, dedupe, rerank) runs without the server:

```bash
uv run python -m bookshelf.discover "dune frank herbert" --limit 5
uv run python -m bookshelf.discover "cozy fantasy" --no-rerank      # Open Library order
uv run python -m bookshelf.discover "cozy fantasy" --json            # full response
uv run python -m bookshelf.discover "dune" --db data/other.db --include-owned
```

The first rerank downloads the model; later runs print `cached · reranked` in the summary.


## Ask the bookshelf

`POST /recommend` and the `/ask` page run a small tool-calling loop: the model picks tools,
the server executes them against your SQLite library, and the model answers from the results.

```bash
curl -s http://127.0.0.1:8000/recommend \
  -H 'content-type: application/json' \
  -d '{"query": "What should I read after Dune?", "max_steps": 4}' | jq
```

The response includes `answer`, `provider`, `model`, and every `steps[]` entry with the tool
name, arguments, and result. `max_steps` (1–8, default `LLM_MAX_STEPS`) caps how many model
turns run; when the budget runs out the loop asks once more for a plain answer.

### Ask from the CLI

The same loop runs without the server, using the provider set by `LLM_PROVIDER`:

```bash
uv run python -m bookshelf.ask "What should I read after Dune?"
uv run python -m bookshelf.ask "cozy fantasy I haven't read" --steps       # show tool calls
uv run python -m bookshelf.ask "short sci-fi" --max-steps 3 --no-rerank
uv run python -m bookshelf.ask "what next?" --model qwen3:8b       # override the model for one run
uv run python -m bookshelf.ask "what next?" --json --db data/other.db
```

Exit codes: `0` success, `1` the LLM request failed, `2` invalid arguments. Tool failures (for
example Open Library being unreachable) are returned to the model rather than aborting the run.

### Multi-turn conversations

Pass a session id (1-200 printable ASCII characters) to make questions share memory:
`--session-id` on `bookshelf.ask`, `"session_id"` in the `POST /recommend` body, or
`?session_id=` on `/ask`. The last 6 question/answer pairs of that session are replayed to the
model, so follow-ups like "something more recent?" work. Without a session id every question is
stateless.

```bash
uv run python -m bookshelf.ask --session-id austen "What should I read after Jane Austen?"
uv run python -m bookshelf.ask --session-id austen "Something more recent?"
```

The `/ask` page has controls for all of this: a **Session** field (remembered in your browser,
with a "New session" button), a **Provider** and **Model** picker (OpenAI is only selectable when
`OPENAI_API_KEY` is set), **Max steps**, and **Skip rerank**. Earlier turns of the session are
listed under the form, with a button to clear that session's memory. Choosing OpenAI there sends
the question to the hosted API exactly as `LLM_PROVIDER=openai` does.

Memory is stored locally in the `conversation_turns` table (question and answer text only, never
tool results or reviews) and stays until you delete those rows. Replayed turns go to the
configured LLM provider like any other message. The same id also groups the runs into one
Langfuse session when tracing is on.

### Langfuse tracing (optional)

Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL` in `.env` and every agent
run (`/recommend`, `/ask`, `bookshelf.ask`) is recorded as one `recommend` trace with a
`chat` generation per model turn and a `tool:<name>` observation per tool call.

**Privacy:** a trace contains your question, the tool arguments and results (titles, authors,
status, ratings; never review text) and the model's output, and it is sent to `LANGFUSE_BASE_URL`
(Langfuse Cloud by default) even when `LLM_PROVIDER=ollama`. Leave the keys unset, or set
`LANGFUSE_TRACING_ENABLED=false`, to send nothing. Tracing failures never fail a request.

### Docker

The **Stop app** button exits the server process, but the compose service uses `restart: unless-stopped`, so Docker starts it again. Use `docker compose stop` to stop it for good.

Every command below is run from the repo root. `docker compose` is the easy path; `docker run`
is the same thing spelled out.

**Run the API**

```bash
docker compose up --build -d     # API on http://127.0.0.1:8000
docker compose logs -f           # follow logs
docker compose down              # stop
```

```bash
docker build -t bookshelf:local .
docker run -d --name bookshelf \
  -p 127.0.0.1:8000:8000 \
  --env-file .env \
  -e BOOKSHELF_DB_PATH=/data/bookshelf.db \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434/v1 \
  --add-host host.docker.internal:host-gateway \
  -v "$PWD/data:/data" -v bookshelf-models:/models \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true \
  bookshelf:local
curl -s http://127.0.0.1:8000/health
```

`docker run --env-file` keeps quote characters literally (compose strips them), so for `docker
run` write `.env` values unquoted, e.g. `LANGFUSE_BASE_URL=https://cloud.langfuse.com`.

**Run the CLIs**

The same image runs the CLIs: put the command after the image name. They use the same `.env`,
`./data` DB and model cache as the API, and need no published port.

```bash
# compose: nothing else to type
docker compose run --rm bookshelf python -m bookshelf.ingest.goodreads /data/goodreads_library_export.csv
docker compose run --rm bookshelf python -m bookshelf.ask "What should I read after Dune?" --steps
docker compose run --rm bookshelf python -m bookshelf.discover "dune frank herbert" --limit 5

# plain docker: define the options once
DRUN='docker run --rm --env-file .env -e BOOKSHELF_DB_PATH=/data/bookshelf.db
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
  --add-host host.docker.internal:host-gateway
  -v '"$PWD"'/data:/data -v bookshelf-models:/models
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true bookshelf:local'
$DRUN python -m bookshelf.ask "cozy fantasy I haven't read" --max-steps 3
$DRUN python -m bookshelf.discover "dune" --no-rerank --json
```

Put the CSV in `./data` first; inside the container it appears under `/data`. The container
runs as a non-root user (uid 10001), so on Linux `./data` must be writable by it
(`chown 10001 data`); Docker Desktop on macOS handles this for you.

The compose file publishes the port on `127.0.0.1` only, mounts `./data` (your DB is never copied
into the image), reads `.env` at runtime, runs as a non-root user with a read-only filesystem and
no capabilities, and caches the reranker model in a named volume. Ollama runs on the host: the
container reaches it at `host.docker.internal:11434`. This has not been built or run yet; the
first build downloads torch and is large.

### Tools

| Tool | Purpose |
|---|---|
| `search_library` | Search your own books by title/author; filter by status or rating |
| `library_stats` | Counts, rating histogram, average rating, top authors/shelves |
| `discover_books` | Open Library search (cached, deduped, reranked) for books you do not own |
| `get_book` | One library book by numeric id |

Tool output is compact JSON. It never includes review text — only `has_review`.
`search_library` falls back to typo-tolerant matching when an exact substring search finds nothing;
such results carry `"fuzzy": true` and a note, and respect the status/rating filters.

### Choose a provider

Both providers use the OpenAI chat-completions API, so the same client code runs either way.
Switch with one variable in `.env`:

```bash
# Local and private (default)
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3.5:4b
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1

# Hosted
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-6-luna
OPENAI_BASE_URL=https://api.openai.com/v1
```

- For Ollama, run `ollama serve` and `ollama pull <model>` first. Use a model that supports
  tool calling (for example `qwen3.5:4b`); the server calls `POST /v1/chat/completions`.
- These names have no `BOOKSHELF_` prefix on purpose, so existing `.env` files keep working.
- `LLM_TIMEOUT_SECONDS` and `LLM_TEMPERATURE` tune the request; `LLM_MAX_STEPS` sets the
  default tool-call budget.
- Errors from the provider return `502` with a short message; the `/ask` page shows it inline.

### Ask from the CLI

The same `agent.recommend` loop runs without the server:

```bash
uv run python -m bookshelf.ask "What should I read after Dune?"
uv run python -m bookshelf.ask "Which unread book should I start?" --steps
uv run python -m bookshelf.ask "Cozy fantasy?" --max-steps 2 --no-rerank
uv run python -m bookshelf.ask "Recommend something" --json
uv run python -m bookshelf.ask "What next?" --db data/other.db
```

`--steps` prints each tool call and result before the answer; `--json` prints the full
`Recommendation`; `--no-rerank` skips the local cross-encoder in `discover_books` calls. Exit
codes: `0` ok, `1` LLM failure, `2` bad arguments.

### MCP server

The same four tools are exposed over MCP stdio, so an MCP client can use them without the API:

```bash
uv run python -m bookshelf.mcp_server
```

Example Claude Desktop entry (use the absolute path to this repository):

```json
{
  "mcpServers": {
    "bookshelf": {
      "command": "uv",
      "args": ["run", "python", "-m", "bookshelf.mcp_server"],
      "cwd": "/absolute/path/to/book-recommendation"
    }
  }
}
```

The server reads `BOOKSHELF_DB_PATH` (or `.env`) and opens one short-lived SQLite connection
per call. It does not need the FastAPI server to be running.


## Tests and checks

```bash
uv run pytest
uv run pytest tests/test_ingest_goodreads.py::test_import_report_counts
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Tests create a temporary SQLite database and never touch `data/`. Open Library is always mocked
via `httpx.MockTransport` or a patched `fetch_search`, reranking is tested with a fake
`Scorer`, and the LLM loop is tested with a fake chat client plus `httpx.MockTransport`, so the
suite needs no network, no model weights, and no API key.

## Architecture

```
src/bookshelf/
├── main.py            FastAPI app factory + lifespan DB init
├── config.py          pydantic-settings (BOOKSHELF_* plus bare LLM_* names)
├── db.py              connections, pragmas, schema init
├── schema.sql         authors, books, library_entries, import_runs, remote_cache
├── models.py          Pydantic API models
├── repository.py      SQL queries
├── services.py        shared business logic (API, CLI, tools)
├── openlibrary.py     Open Library HTTP client + parsing
├── matching.py        title/author normalization for dedupe
├── rerank.py          lazy local cross-encoder scoring
├── discover.py        discovery CLI (same service layer as the API)
├── tools.py           tool specs + handlers shared by the agent and MCP server
├── llm.py             one OpenAI-compatible chat client for OpenAI and Ollama
├── agent.py           tool-calling retrieval loop
├── ask.py             ask CLI (same loop as /recommend and /ask)
├── mcp_server.py      MCP stdio server exposing the tools
├── web.py             server-rendered HTML pages
├── api/               thin FastAPI adapters
└── ingest/goodreads.py  CSV parser, upserts, CLI
```

- API routes call `services.py`; only `repository.py` and the importer contain SQL.
- `openlibrary.py` is the only module that makes Open Library calls; `llm.py` is the only module
  that talks to an LLM provider. `rerank.py` only downloads a model from Hugging Face on first
  use; inference stays local.
- `agent.recommend` and `mcp_server` both go through `tools.call_tool`, so the tool set and its
  privacy rules live in one place. Configure the provider with `LLM_PROVIDER`; no agent code is
  provider-specific.
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
4. **M4 (done):** MCP tools and the LLM-driven retrieval loop, with Ollama and OpenAI through
   one client.
5. **M5 (done, sandbox deferred):** Docker and Langfuse tracing. The sandbox for dynamic
   analysis is deferred because nothing executes model-written code yet.
6. **M6:** Retrieval evaluations and local-vs-hosted model comparison.
