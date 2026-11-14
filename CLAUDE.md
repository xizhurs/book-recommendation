# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

`AGENTS.md` is the source of truth for commands, architecture, layering rules, and privacy
constraints. Keep it updated there rather than duplicating it here. `README.md` has user-facing
setup and the privacy summary.

## Key points to keep in mind

- Request flow is `api/routes.py` → `services.py` → `repository.py` (SQL only). The CLIs
  (`discover`, `ask`) and the MCP server reuse `services.discover` / `tools.call_tool` / `agent.recommend`;
  never reimplement cache, dedupe, rerank, tool, or SQL logic in an entry point.
- Never read or open anything under `data/` (real personal export and DB). Tests use
  `tests/fixtures/goodreads_sample.csv` and temp DBs from `tests/conftest.py`, with fake LLM clients,
  `httpx.MockTransport`, and fake rerank scorers. No real network or model downloads in tests.
- LLM tool results must never contain review text (only `has_review`).
- Schema changes must be additive `CREATE ... IF NOT EXISTS` in `schema.sql` (no migration framework).
- Scope: M4 is done. Do not add Docker, Langfuse, sandboxes (M5), or evaluations (M6) yet.
