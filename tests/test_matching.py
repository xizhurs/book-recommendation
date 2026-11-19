from __future__ import annotations

import pytest

from bookshelf.matching import edit_distance, fuzzy_score


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("dune", "dune", 0), ("dune", "dnue", 1), ("herbert", "hebert", 1), ("abc", "xyz", 3)],
)
def test_edit_distance(a: str, b: str, expected: int) -> None:
    assert edit_distance(a, b) == expected


@pytest.mark.parametrize(
    "query",
    ["dnue", "Frank Hebert", "piranesy", "left hand darkness", "dispossesed", "ursla le guin"],
)
def test_typos_match(query: str) -> None:
    texts = [
        "Dune Frank Herbert",
        "Piranesi Susanna Clarke",
        "The Left Hand of Darkness Ursula K. Le Guin",
        "The Dispossessed Ursula K. Le Guin",
    ]
    assert any(fuzzy_score(query, text) > 0 for text in texts)


def test_every_query_word_must_match() -> None:
    assert fuzzy_score("dune zzzzzz", "Dune Frank Herbert") == 0.0


def test_short_words_must_match_exactly() -> None:
    assert fuzzy_score("dun", "Dune Frank Herbert") == 0.0


def test_exact_match_scores_higher_than_a_typo() -> None:
    assert fuzzy_score("dune", "Dune") > fuzzy_score("dnue", "Dune")


def test_empty_inputs_score_zero() -> None:
    assert fuzzy_score("", "Dune") == 0.0
    assert fuzzy_score("dune", "") == 0.0
