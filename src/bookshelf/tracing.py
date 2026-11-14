"""Optional Langfuse tracing for the agent loop.

Tracing is a no-op unless ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set. When it
is on, the question, tool arguments/results, and model output are sent to ``LANGFUSE_BASE_URL``
(review text is never in tool results). The ``langfuse`` import stays inside the lazy builder so
untraced runs and tests never load it, and tracing failures never break a request.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from functools import lru_cache
from typing import Any, Protocol

from .config import TracingSettings

logger = logging.getLogger(__name__)


class Observation(Protocol):
    def update(self, **fields: Any) -> None: ...


class Tracer(Protocol):
    def observe(
        self,
        name: str,
        *,
        as_type: str = "span",
        input: Any = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[Observation]: ...

    def flush(self) -> None: ...


class _NoopObservation:
    def update(self, **fields: Any) -> None:
        return None


class NoopTracer:
    @contextmanager
    def observe(
        self,
        name: str,
        *,
        as_type: str = "span",
        input: Any = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Observation]:
        yield _NoopObservation()

    def flush(self) -> None:
        return None


class LangfuseTracer:
    """Adapter over a Langfuse client (anything with ``start_as_current_observation``)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @contextmanager
    def observe(
        self,
        name: str,
        *,
        as_type: str = "span",
        input: Any = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Observation]:
        fields: dict[str, Any] = {"name": name, "as_type": as_type, "input": input}
        if model is not None:
            fields["model"] = model
        if metadata:
            fields["metadata"] = metadata
        try:
            manager = self._client.start_as_current_observation(**fields)
            observation = manager.__enter__()
        except Exception:
            logger.warning("Langfuse tracing failed to start %r", name, exc_info=True)
            yield _NoopObservation()
            return
        try:
            yield _SafeObservation(observation)
        except BaseException as exc:
            _close(manager, type(exc), exc, exc.__traceback__)
            raise
        else:
            _close(manager, None, None, None)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:
            logger.warning("Langfuse flush failed", exc_info=True)


class _SafeObservation:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def update(self, **fields: Any) -> None:
        try:
            self._inner.update(**fields)
        except Exception:
            logger.warning("Langfuse update failed", exc_info=True)


def _close(manager: Any, exc_type: Any, exc: Any, traceback: Any) -> None:
    try:
        manager.__exit__(exc_type, exc, traceback)
    except Exception:
        logger.warning("Langfuse tracing failed to close an observation", exc_info=True)


_NOOP = NoopTracer()


def get_tracer(settings: TracingSettings) -> Tracer:
    """The process-wide tracer for these settings (no-op when tracing is not configured)."""
    if not settings.enabled or settings.langfuse_secret_key is None:
        return _NOOP
    assert settings.langfuse_public_key is not None
    return _build_langfuse(
        settings.langfuse_public_key,
        settings.langfuse_secret_key.get_secret_value(),
        settings.langfuse_base_url,
    )


@lru_cache(maxsize=2)
def _build_langfuse(public_key: str, secret_key: str, base_url: str) -> Tracer:
    from langfuse import Langfuse

    return LangfuseTracer(Langfuse(public_key=public_key, secret_key=secret_key, base_url=base_url))


def flush(settings: TracingSettings) -> None:
    """Send any buffered traces; call before a short-lived process exits."""
    get_tracer(settings).flush()
