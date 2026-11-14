from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BOOKSHELF_",
        extra="ignore",
    )

    db_path: Path = Path("data/bookshelf.db")
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # M2: Open Library discovery. Responses are cached in SQLite and every search is
    # capped by a request budget so a bug or a clicked-again page cannot hammer the API.
    openlibrary_base_url: str = "https://openlibrary.org"
    openlibrary_timeout_seconds: float = 10.0
    openlibrary_cache_ttl_seconds: int = 86400
    openlibrary_max_requests: int = 3
