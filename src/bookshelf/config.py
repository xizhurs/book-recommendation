from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    """LLM provider settings.

    These deliberately have no ``BOOKSHELF_`` prefix so the bare names already used in
    ``.env`` (``LLM_PROVIDER``, ``OPENAI_API_KEY``, ...) keep working. Both providers speak
    the OpenAI chat-completions API, so switching is one environment variable.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    llm_provider: Literal["openai", "ollama"] = "ollama"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-6-luna"
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_model: str = "qwen3.5:4b"
    ollama_base_url: str = "http://127.0.0.1:11434/v1"

    llm_timeout_seconds: float = 90.0
    llm_max_steps: int = 4
    llm_temperature: float = 0.2


class TracingSettings(BaseSettings):
    """Langfuse tracing: off unless both keys are set, or when ``LANGFUSE_TRACING_ENABLED=false``.

    Bare ``LANGFUSE_*`` names are what the Langfuse docs use. When enabled, agent runs (the
    question, tool arguments and results, model output) are sent to ``langfuse_base_url``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_tracing_enabled: bool = True

    @property
    def enabled(self) -> bool:
        return (
            self.langfuse_tracing_enabled
            and bool(self.langfuse_public_key)
            and self.langfuse_secret_key is not None
            and bool(self.langfuse_secret_key.get_secret_value())
        )


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

    # M3: local cross-encoder reranking. Loaded lazily on first use; disable to stay offline.
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    rerank_candidates: int = 25

    # M4: LLM provider for the recommendation loop (bare env names, see LLMSettings).
    llm: LLMSettings = Field(default_factory=LLMSettings)
    tracing: TracingSettings = Field(default_factory=TracingSettings)
