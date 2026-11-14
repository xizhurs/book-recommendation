from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.routes import books_router, router
from .config import Settings
from .db import connect, init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    conn = connect(app.state.db_path)
    try:
        init_db(conn)
    finally:
        conn.close()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="AI Bookshelf", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db_path = settings.db_path
    app.include_router(router)
    app.include_router(books_router)
    return app


app = create_app()
