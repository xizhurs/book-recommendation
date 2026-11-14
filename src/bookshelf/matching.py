"""Normalisation used to decide whether a discovery candidate is already owned."""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalize_name(value: str) -> str:
    """Lowercase and strip punctuation so "Le Guin, Ursula" can match "Ursula K. Le Guin"."""
    return _NON_ALNUM.sub(" ", value.lower()).strip()


def title_author_key(title: str, author: str | None) -> tuple[str, str]:
    return normalize_name(title), normalize_name(author or "")


MIN_FUZZY_TOKEN_LENGTH = 4
FUZZY_TOKEN_THRESHOLD = 0.75


def edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance: insert, delete, substitute, swap adjacent letters."""
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            rows[i][j] = min(
                rows[i - 1][j] + 1,
                rows[i][j - 1] + 1,
                rows[i - 1][j - 1] + cost,
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[len(a)][len(b)]


def _token_similarity(query_token: str, candidate_token: str) -> float:
    if query_token == candidate_token:
        return 1.0
    if len(query_token) < MIN_FUZZY_TOKEN_LENGTH:
        return 0.0  # short words must match exactly; one typo changes too much of them
    longest = max(len(query_token), len(candidate_token))
    return 1.0 - edit_distance(query_token, candidate_token) / longest


def fuzzy_score(query: str, text: str) -> float:
    """How well ``text`` matches ``query`` despite typos, from 0.0 (no match) to 1.0.

    Every query word must match some word in ``text`` at ``FUZZY_TOKEN_THRESHOLD`` or better;
    otherwise the score is 0.0. Otherwise it is the mean of the best per-word similarities.
    """
    query_tokens = normalize_name(query).split()
    text_tokens = normalize_name(text).split()
    if not query_tokens or not text_tokens:
        return 0.0
    best: list[float] = []
    for query_token in query_tokens:
        similarity = max(_token_similarity(query_token, token) for token in text_tokens)
        if similarity < FUZZY_TOKEN_THRESHOLD:
            return 0.0
        best.append(similarity)
    return sum(best) / len(best)
