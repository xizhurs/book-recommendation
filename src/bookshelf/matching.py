"""Normalisation used to decide whether a discovery candidate is already owned."""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_name(value: str) -> str:
    """Lowercase and strip punctuation so "Le Guin, Ursula" can match "Ursula K. Le Guin"."""
    return _NON_ALNUM.sub(" ", value.lower()).strip()


def title_author_key(title: str, author: str | None) -> tuple[str, str]:
    return normalize_name(title), normalize_name(author or "")
