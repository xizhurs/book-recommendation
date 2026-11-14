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
