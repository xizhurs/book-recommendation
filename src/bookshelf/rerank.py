"""Local cross-encoder reranking for discovery candidates.

Importing this module stays cheap: torch and sentence-transformers are only imported when a
model is actually loaded, and the model is cached per process. Tests inject a fake ``Scorer``
so the suite never downloads weights.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from threading import Lock
from typing import Any, Protocol

DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"


class Scorer(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


class CrossEncoderScorer:
    """Scores (query, document) pairs with a local cross-encoder on CPU."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._lock = Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import CrossEncoder

                    self._model = CrossEncoder(self.model_name, device="cpu")
        pairs = [(query, document) for document in documents]
        return [float(score) for score in self._model.predict(pairs)]


@lru_cache(maxsize=4)
def get_scorer(model_name: str = DEFAULT_MODEL) -> Scorer:
    """Return a process-wide scorer so the model is loaded at most once per model name."""
    return CrossEncoderScorer(model_name)


def describe(title: str, author: str | None, year: int | None) -> str:
    """Build the document text that gets scored against the query."""
    text = title
    if author:
        text = f"{title} — {author}"
    if year is not None:
        text = f"{text} ({year})"
    return text


def order(scores: Sequence[float]) -> list[int]:
    """Indices sorted by descending score, keeping input order on ties."""
    return sorted(range(len(scores)), key=lambda index: (-scores[index], index))
