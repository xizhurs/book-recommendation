# syntax=docker/dockerfile:1
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    HF_HOME=/models \
    BOOKSHELF_DB_PATH=/data/bookshelf.db

WORKDIR /app

# Dependencies first so code edits do not invalidate the (large) torch layer.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# Unprivileged user; /data holds the SQLite DB, /models the cached cross-encoder.
RUN useradd --create-home --uid 10001 bookshelf \
    && mkdir -p /data /models \
    && chown bookshelf:bookshelf /data /models
USER bookshelf

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Binds all interfaces *inside* the container; compose publishes it on 127.0.0.1 only.
CMD ["uvicorn", "bookshelf.main:app", "--host", "0.0.0.0", "--port", "8000"]
